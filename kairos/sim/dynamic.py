"""Disruption engine and dynamic replanning (SYNTHETIC events, real algorithms).

Workflow for one disruption at time ``tau``:

1. **Observe state.** The plan is executed up to ``tau`` in one realised
   world (a seeded scenario). Each vehicle has completed some stops and is
   committed to the stop it is driving to or serving at ``tau``.
2. **Apply the event.** Traffic, weather and service shocks change the
   planning inputs from ``tau`` onwards; a breakdown removes a vehicle (its
   committed and remaining stops become orphaned); an urgent order adds a new
   stop with a tight window.
3. **Re-plan the residual problem** with PyVRP. Each active vehicle becomes
   its own vehicle type starting at a pseudo-depot located where it becomes
   available (its committed stop), from the expected time it finishes there;
   idle vehicles start at the main depot at ``tau``. Policies:
     * ``hold``        keep remaining sequences; orphaned/new stops are added
                       by cheapest insertion (local-repair baseline);
     * ``reoptimise``  full PyVRP re-solve on expected (disrupted) times;
     * ``reliability`` re-solve with the reliability planner's buffer ladder
                       and in-sample selection against the target.
4. **Evaluate** every policy on the same out-of-sample scenarios of the
   residual horizon (common random numbers), and diff the plans.

Simplifying assumptions (documented in docs/METHOD.md): packages of a
broken-down vehicle can be transferred to other vehicles; the planner knows
the event's magnitude once it occurs; events persist for ``duration``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable

import numpy as np

from kairos.config import EVALUATION_SEED_OFFSET, PLANNING_SEED_OFFSET
from kairos.data.schema import Instance
from kairos.sim.montecarlo import Effects, RouteSpec, simulate, stop_profiles
from kairos.solver.planners import DEFAULT_LADDER, FIRST_SHARE, Candidate, select_candidate, split_budget
from kairos.solver.vrp import DepotSpec, RoutingProblem, SolveResult, VehicleSpec, solve_problem
from kairos.uncertainty.stochastic import UncertaintyConfig, iter_scenarios, service_sd, travel_sd

EVENT_TYPES = ("traffic", "breakdown", "urgent_order", "service_shock", "weather")
POLICIES = ("hold", "reoptimise", "reliability")

# estimator(inst, location) -> (tt_from_new, tt_to_new, rel_sd_from, rel_sd_to)
Estimator = Callable[[Instance, np.ndarray], tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]


@dataclass
class DisruptionEvent:
    type: str
    time: float  # when the event occurs / becomes known (instance time units)
    factor: float = 1.5  # multiplier for traffic / weather / service shocks
    center: tuple[float, float] | None = None  # affected area centre (instance coords)
    radius: float | None = None  # affected radius (coord units; km for wgs84)
    vehicle: int | None = None  # breakdown: route index
    duration: float | None = None  # effect duration (None = rest of day)
    location: tuple[float, float] | None = None  # urgent order location
    window: float | None = None  # urgent order window width
    service: float | None = None
    demand: float = 0.0

    def validate(self, inst: Instance) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {self.type!r}; choose one of {EVENT_TYPES}")
        if not inst.tw_early[0] <= self.time < inst.tw_late[0]:
            raise ValueError("event time must fall inside the planning horizon")
        if self.type in ("traffic", "weather", "service_shock") and not 0.2 <= self.factor <= 5:
            raise ValueError("factor must lie in [0.2, 5]")
        if self.type == "urgent_order" and self.location is None:
            raise ValueError("urgent_order requires a location")

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class VehicleState:
    route_index: int
    completed: list[int]  # stops finished before tau
    committed: int | None  # stop being driven to / served at tau
    position: int  # node where the vehicle becomes available for new decisions
    available_at: float  # expected time it becomes available there
    remaining: list[int]  # planned stops still to visit after the committed one
    status: str  # "en_route" | "returned" | "not_started"


@dataclass
class SystemState:
    tau: float
    vehicles: list[VehicleState]
    idle_vehicles: int  # unused fleet available at the depot


def _haversine_km(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    lng1, lat1 = np.radians(a[..., 0]), np.radians(a[..., 1])
    lng2, lat2 = np.radians(b[..., 0]), np.radians(b[..., 1])
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(h))


def distance_to(inst: Instance, center: tuple[float, float]) -> np.ndarray:
    c = np.asarray(center, dtype=float)
    if inst.coord_system == "wgs84":
        return _haversine_km(inst.coords, np.broadcast_to(c, inst.coords.shape))
    return np.sqrt(((inst.coords - c) ** 2).sum(1))


# ---------------------------------------------------------------------------
# 1. State observation
# ---------------------------------------------------------------------------


def observe_state(
    inst: Instance,
    routes: list[RouteSpec],
    tau: float,
    cfg: UncertaintyConfig,
    world_seed: int,
) -> tuple[SystemState, np.ndarray]:
    """Execute the plan in one realised world up to ``tau``.

    The planner then knows each vehicle's realised progress, but not future
    noise: the time a vehicle finishes its committed stop is the *expected*
    completion given what has been observed so far. Returns the state and the
    realised arrival times observed before ``tau``.
    """
    active_routes = [r for r in routes if r.stops]
    blk = next(iter_scenarios(inst, cfg, 1, world_seed, n_vehicles=max(len(routes), inst.num_vehicles)))
    arrivals = np.full(inst.n_nodes, np.nan)
    states: list[VehicleState] = []
    for ri, r in enumerate(active_routes):
        t = inst.tw_early[0] if r.start_time is None else r.start_time
        prev = r.start_node
        completed: list[int] = []
        committed: int | None = None
        position, available = prev, max(t, tau)
        status = "not_started" if t >= tau else "en_route"
        if status == "en_route":
            for node in r.stops:
                depart = t
                if depart >= tau:  # waiting at ``prev`` before departing
                    position, available = prev, depart
                    break
                factor = blk.day[0] * blk.vehicle[0, r.vehicle] * blk.arc[0, prev, node]
                arrive = depart + inst.travel_time[prev, node] * factor
                begin = max(arrive, inst.tw_early[node])
                end = begin + inst.service[node] * blk.service[0, node]
                if arrive <= tau:
                    arrivals[node] = arrive
                if end <= tau:
                    completed.append(node)
                    t, prev = end, node
                    continue
                committed, position = node, node
                if arrive > tau:  # still driving: expected arrival given elapsed time
                    exp_arrive = max(depart + inst.travel_time[prev, node], tau)
                    available = max(exp_arrive, inst.tw_early[node]) + inst.service[node]
                else:  # waiting or serving
                    available = max(begin + inst.service[node], tau)
                break
            else:
                status, position = "returned", 0
                available = max(t + inst.travel_time[prev, 0], tau)
        done = set(completed) | ({committed} if committed is not None else set())
        remaining = [s for s in r.stops if s not in done]
        states.append(VehicleState(ri, completed, committed, int(position), float(available), remaining, status))
    idle = max(0, inst.num_vehicles - len(active_routes))
    return SystemState(tau, states, idle), arrivals


# ---------------------------------------------------------------------------
# 2. Event application
# ---------------------------------------------------------------------------


@dataclass
class DisruptedWorld:
    inst: Instance  # possibly extended with a new urgent stop
    effects: Effects  # true effects of the event from tau
    planning_travel: np.ndarray  # planner's expected travel times after the event
    planning_service: np.ndarray
    new_node: int | None = None
    broken_route: int | None = None
    affected_nodes: list[int] = field(default_factory=list)
    description: str = ""


def _extend_with_order(inst: Instance, ev: DisruptionEvent, estimator: Estimator | None) -> tuple[Instance, int]:
    """Append a new stop for an urgent order. Travel times to/from it come from
    ``estimator`` (the calibrated travel-time model) when available, else from
    geometry (Euclidean benchmark convention)."""
    loc = np.asarray(ev.location, dtype=float)
    n = inst.n_nodes
    if estimator is not None:
        tt_out, tt_in, rel_out, rel_in = estimator(inst, loc)
    else:
        d = distance_to(inst, (float(loc[0]), float(loc[1])))
        tt_out = tt_in = d
        rel_out = rel_in = np.zeros(n)
    tt = np.zeros((n + 1, n + 1))
    tt[:n, :n] = inst.travel_time
    tt[:n, n], tt[n, :n] = tt_in, tt_out
    dist = np.zeros_like(tt)
    dist[:n, :n] = inst.distance
    if inst.coord_system == "euclidean":
        geo = distance_to(inst, (float(loc[0]), float(loc[1])))
        dist[:n, n] = dist[n, :n] = geo
    else:  # Amazon instances use expected driving time as travel cost
        dist[:n, n], dist[n, :n] = tt_in, tt_out
    rel = np.zeros_like(tt)
    rel[:n, :n] = inst.tt_rel_sd
    rel[:n, n], rel[n, :n] = rel_in, rel_out
    obs = np.zeros((n + 1, n + 1), dtype=bool)
    obs[:n, :n] = inst.tt_observed
    obs[n, n] = True
    window = ev.window if ev.window is not None else 0.25 * (inst.tw_late[0] - inst.tw_early[0])
    service = ev.service if ev.service is not None else float(np.median(inst.service[1:]))
    new = replace(
        inst,
        id=inst.id + "+urgent",
        coords=np.vstack([inst.coords, loc]),
        travel_time=tt,
        distance=dist,
        service=np.append(inst.service, service),
        tw_early=np.append(inst.tw_early, ev.time),
        tw_late=np.append(inst.tw_late, min(ev.time + window, inst.tw_late[0])),
        demand=np.append(inst.demand, min(ev.demand, inst.capacity)),
        has_tw=np.append(inst.has_tw, True),
        tt_observed=obs,
        tt_rel_sd=rel,
        stop_ids=inst.stop_ids + ["URGENT"],
        zones=inst.zones + [None],
    )
    return new, n


def apply_event(inst: Instance, ev: DisruptionEvent, estimator: Estimator | None = None) -> DisruptedWorld:
    ev.validate(inst)
    end = ev.time + ev.duration if ev.duration else np.inf
    new_node = None
    if ev.type == "urgent_order":
        inst, new_node = _extend_with_order(inst, ev, estimator)
    n = inst.n_nodes
    tf = np.ones((n, n))
    sf = np.ones(n)
    affected: list[int] = []
    if ev.type in ("traffic", "weather", "service_shock"):
        if ev.center is not None and ev.radius is not None:
            mask = distance_to(inst, ev.center) <= ev.radius
        else:
            mask = np.ones(n, dtype=bool)
        affected = [int(i) for i in np.flatnonzero(mask) if i != 0]
        if ev.type == "traffic":
            tf = np.where(mask[:, None] | mask[None, :], ev.factor, 1.0)
        elif ev.type == "weather":
            tf[:] = ev.factor
            sf[:] = 1.0 + (ev.factor - 1.0) * 0.5  # assumption: service slows half as much
        else:
            sf = np.where(mask, ev.factor, 1.0)
    effects = Effects(start_time=ev.time, travel_factor=tf, service_factor=sf, end_time=end)
    desc = {
        "traffic": f"Traffic delay x{ev.factor:.2f} on arcs touching {len(affected)} stops",
        "weather": f"Adverse weather: travel x{ev.factor:.2f}, service x{sf.max():.2f}",
        "service_shock": f"Service-duration shock x{ev.factor:.2f} at {len(affected)} stops",
        "breakdown": f"Vehicle {(ev.vehicle or 0) + 1} breaks down",
        "urgent_order": "Urgent order released",
    }[ev.type]
    return DisruptedWorld(
        inst=inst,
        effects=effects,
        planning_travel=inst.travel_time * tf,
        planning_service=inst.service * sf,
        new_node=new_node,
        broken_route=ev.vehicle if ev.type == "breakdown" else None,
        affected_nodes=affected,
        description=desc,
    )


# ---------------------------------------------------------------------------
# 3. Residual problem and policies
# ---------------------------------------------------------------------------


@dataclass
class ResidualPlan:
    policy: str
    routes: list[RouteSpec]  # start_node / start_time set per vehicle
    vehicle_labels: list[int]  # original route index (-1 = dispatched spare vehicle)
    solve: SolveResult | None
    runtime: float
    beta: float = 0.0
    unserved: list[int] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)


def _active_vehicles(state: SystemState, broken: int | None) -> list[VehicleState]:
    return [v for v in state.vehicles if v.route_index != broken and v.status != "returned"]


def _orphans(state: SystemState, broken: int | None) -> list[int]:
    out: list[int] = []
    for v in state.vehicles:
        if v.route_index == broken:
            out += ([v.committed] if v.committed is not None else []) + v.remaining
    return out


def _start_of(v: VehicleState, tau: float) -> tuple[int, float]:
    return v.position, max(v.available_at, tau)


def _pending(world: DisruptedWorld, state: SystemState) -> list[int]:
    extra = [world.new_node] if world.new_node is not None else []
    return _orphans(state, world.broken_route) + extra


def build_residual(
    world: DisruptedWorld, state: SystemState, travel: np.ndarray, service: np.ndarray
) -> tuple[RoutingProblem, list[int]]:
    inst = world.inst
    active = _active_vehicles(state, world.broken_route)
    clients = [s for v in active for s in v.remaining] + _pending(world, state)
    depots = [DepotSpec(0, inst.tw_early[0], inst.tw_late[0])]
    vehicles: list[VehicleSpec] = []
    labels: list[int] = []
    for v in active:
        node, start = _start_of(v, state.tau)
        if node == 0:
            dep = 0
        else:
            depots.append(DepotSpec(node, start, inst.tw_late[0]))
            dep = len(depots) - 1
        delivered = v.completed + ([v.committed] if v.committed is not None else [])
        vehicles.append(
            VehicleSpec(
                start_depot=dep,
                end_depot=0,
                tw_early=start,
                tw_late=inst.tw_late[0],
                capacity=max(inst.capacity - float(inst.demand[delivered].sum()), 1e-6),
                name=f"vehicle-{v.route_index}",
            )
        )
        labels.append(v.route_index)
    if state.idle_vehicles > 0:
        vehicles.append(
            VehicleSpec(
                start_depot=0,
                end_depot=0,
                num_available=state.idle_vehicles,
                tw_early=state.tau,
                tw_late=inst.tw_late[0],
                capacity=inst.capacity,
                fixed_cost=inst.vehicle_fixed_cost,
                name="spare",
            )
        )
        labels.append(-1)
    return RoutingProblem(inst, sorted(set(clients)), depots, vehicles, travel, service), labels


def _routes_from_residual(
    prob: RoutingProblem, sol: SolveResult, labels: list[int]
) -> tuple[list[RouteSpec], list[int]]:
    routes, vlabels = [], []
    for r in sol.routes:
        dep = prob.depots[r.start_depot]
        vt = prob.vehicles[r.vehicle_type]
        routes.append(RouteSpec(stops=list(r.stops), start_node=dep.node, start_time=vt.tw_early, vehicle=len(routes)))
        vlabels.append(labels[r.vehicle_type])
    return routes, vlabels


def hold_policy(world: DisruptedWorld, state: SystemState) -> ResidualPlan:
    """Keep sequences; insert orphaned / new stops by cheapest insertion
    (minimising added expected lateness, then added travel cost)."""
    t0 = time.perf_counter()
    inst = world.inst
    tt, svc = world.planning_travel, world.planning_service
    active = _active_vehicles(state, world.broken_route)
    seqs: list[list[int]] = [list(v.remaining) for v in active]
    starts = [_start_of(v, state.tau) for v in active]

    def lateness(seq: list[int], start: tuple[int, float]) -> float:
        node, t = start
        late = 0.0
        for s in seq:
            t += tt[node, s]
            if inst.has_tw[s]:
                late += max(0.0, t - inst.tw_late[s])
            t = max(t, inst.tw_early[s]) + svc[s]
            node = s
        return late + max(0.0, t + tt[node, 0] - inst.tw_late[0])

    def cost(seq: list[int], start: tuple[int, float]) -> float:
        path = [start[0], *seq, 0]
        return float(inst.distance[path[:-1], path[1:]].sum())

    unserved: list[int] = []
    for node in _pending(world, state):
        best = None
        for k, seq in enumerate(seqs):
            base = (lateness(seq, starts[k]), cost(seq, starts[k]))
            for pos in range(len(seq) + 1):
                cand = seq[:pos] + [node] + seq[pos:]
                key = (lateness(cand, starts[k]) - base[0], cost(cand, starts[k]) - base[1])
                if best is None or key < best[0]:
                    best = (key, k, pos)
        if best is None:
            unserved.append(node)
        else:
            seqs[best[1]].insert(best[2], node)
    keep = [k for k, seq in enumerate(seqs) if seq]
    routes = [RouteSpec(seqs[k], starts[k][0], starts[k][1], vehicle=i) for i, k in enumerate(keep)]
    labels = [active[k].route_index for k in keep]
    return ResidualPlan("hold", routes, labels, None, time.perf_counter() - t0, unserved=unserved)


def reoptimise_policy(
    world: DisruptedWorld, state: SystemState, iterations: int, seed: int, time_limit: float = 10.0
) -> ResidualPlan:
    t0 = time.perf_counter()
    prob, labels = build_residual(world, state, world.planning_travel, world.planning_service)
    init = [r.stops for r in hold_policy(world, state).routes]
    sol = solve_problem(prob, iterations=iterations, time_limit=time_limit, seed=seed, initial_routes=init)
    routes, vlabels = _routes_from_residual(prob, sol, labels)
    return ResidualPlan("reoptimise", routes, vlabels, sol, time.perf_counter() - t0, unserved=sol.unplanned)


def reliability_policy(
    world: DisruptedWorld,
    state: SystemState,
    cfg: UncertaintyConfig,
    target: float,
    iterations: int,
    seed: int,
    planning_scenarios: int = 60,
    ladder: tuple[float, ...] = DEFAULT_LADDER,
    time_limit: float = 10.0,
) -> ResidualPlan:
    t0 = time.perf_counter()
    inst = world.inst
    t_sd = travel_sd(inst, cfg) * world.effects.travel_factor
    s_sd = service_sd(inst, cfg) * world.effects.service_factor
    budgets = split_budget(iterations, len(ladder), first_share=FIRST_SHARE)
    cands: list[Candidate] = []
    built: list[tuple[list[RouteSpec], list[int]]] = []
    init = [r.stops for r in hold_policy(world, state).routes]
    for i, beta in enumerate(sorted(ladder)):
        prob, labels = build_residual(
            world, state, world.planning_travel + beta * t_sd, world.planning_service + beta * s_sd
        )
        sol = solve_problem(prob, iterations=budgets[i], time_limit=time_limit, seed=seed, initial_routes=init)
        init = [r.stops for r in sol.routes]
        routes, vlabels = _routes_from_residual(prob, sol, labels)
        sim = simulate(inst, routes, cfg, planning_scenarios, seed + PLANNING_SEED_OFFSET, effects=world.effects)
        cands.append(Candidate(beta, seed, sol, sim.metrics))
        built.append((routes, vlabels))
    best, _ = select_candidate(cands, target)
    best.chosen = True
    routes, vlabels = built[cands.index(best)]
    return ResidualPlan(
        "reliability",
        routes,
        vlabels,
        best.solve,
        time.perf_counter() - t0,
        beta=best.beta,
        unserved=best.solve.unplanned,
        candidates=[c.to_dict() for c in cands],
    )


# ---------------------------------------------------------------------------
# 4. Orchestration, evaluation, diff
# ---------------------------------------------------------------------------


def diff_plans(before: dict[int, list[int]], after: dict[int, list[int]]) -> dict[str, Any]:
    """Compare residual stop assignments per vehicle (keys: original route index)."""
    owner_b = {s: v for v, seq in before.items() for s in seq}
    owner_a = {s: v for v, seq in after.items() for s in seq}
    moved = [
        {"stop": s, "from": owner_b.get(s), "to": owner_a.get(s)}
        for s in sorted(set(owner_b) | set(owner_a))
        if owner_b.get(s) != owner_a.get(s)
    ]
    resequenced = []
    for v in set(before) & set(after):
        common_b = [s for s in before[v] if s in set(after[v])]
        common_a = [s for s in after[v] if s in set(before[v])]
        if common_b != common_a:
            resequenced.append(v)
    return {"moved": moved, "n_moved": len(moved), "resequenced_vehicles": sorted(resequenced)}


def run_disruption(
    inst: Instance,
    routes: list[RouteSpec],
    event: DisruptionEvent,
    cfg: UncertaintyConfig,
    *,
    policies: tuple[str, ...] = POLICIES,
    target: float = 0.95,
    iterations: int = 1500,
    seed: int = 0,
    eval_scenarios: int = 200,
    planning_scenarios: int = 60,
    estimator: Estimator | None = None,
    time_limit: float = 10.0,
) -> dict[str, Any]:
    for p in policies:
        if p not in POLICIES:
            raise ValueError(f"unknown policy {p!r}; choose from {POLICIES}")
    active_routes = [r for r in routes if r.stops]
    if event.type == "breakdown" and (event.vehicle is None or not 0 <= event.vehicle < len(active_routes)):
        raise ValueError(f"breakdown requires a vehicle index in [0, {len(active_routes) - 1}]")
    world_seed = seed + EVALUATION_SEED_OFFSET - 1
    state, realised = observe_state(inst, active_routes, event.time, cfg, world_seed)
    world = apply_event(inst, event, estimator)

    plans: dict[str, ResidualPlan] = {}
    for p in policies:
        if p == "hold":
            plans[p] = hold_policy(world, state)
        elif p == "reoptimise":
            plans[p] = reoptimise_policy(world, state, iterations, seed, time_limit)
        else:
            plans[p] = reliability_policy(
                world, state, cfg, target, iterations, seed, planning_scenarios, time_limit=time_limit
            )

    eval_seed = seed + EVALUATION_SEED_OFFSET
    before = {v.route_index: list(v.remaining) for v in state.vehicles if v.remaining}
    for o in _orphans(state, world.broken_route):
        before.setdefault(world.broken_route, [])
        if o not in before[world.broken_route]:
            before[world.broken_route].insert(0, o)
    out_policies: dict[str, Any] = {}
    for name, rp in plans.items():
        sim = simulate(world.inst, rp.routes, cfg, eval_scenarios, eval_seed, effects=world.effects)
        metrics = dict(sim.metrics)
        metrics["unserved"] = len(rp.unserved)
        after: dict[int, list[int]] = {}
        spare = 0
        for lbl, r in zip(rp.vehicle_labels, rp.routes):
            if lbl < 0:
                lbl = 1000 + spare
                spare += 1
            after[lbl] = list(r.stops)
        out_policies[name] = {
            "metrics": metrics,
            "runtime_s": rp.runtime,
            "beta": rp.beta,
            "solver": rp.solve.to_dict() if rp.solve else None,
            "unserved": rp.unserved,
            "candidates": rp.candidates,
            "routes": [
                {"vehicle": lbl, "start_node": r.start_node, "start_time": r.start_time, "stops": r.stops}
                for lbl, r in zip(rp.vehicle_labels, rp.routes)
            ],
            "diff": diff_plans(before, after),
            "stop_profiles": stop_profiles(world.inst, sim),
        }
    return {
        "event": event.to_dict(),
        "description": world.description,
        "tau": event.time,
        "world_seed": world_seed,
        "new_node": world.new_node,
        "affected_nodes": world.affected_nodes,
        "state": {
            "vehicles": [
                {
                    "route_index": v.route_index,
                    "status": "broken" if v.route_index == world.broken_route else v.status,
                    "completed": v.completed,
                    "committed": v.committed,
                    "position": v.position,
                    "available_at": v.available_at,
                    "remaining": v.remaining,
                }
                for v in state.vehicles
            ],
            "idle_vehicles": state.idle_vehicles,
            "n_completed": sum(len(v.completed) for v in state.vehicles),
            "realised_arrivals": {int(i): float(a) for i, a in enumerate(realised) if not np.isnan(a)},
        },
        "instance": world.inst,
        "policies": out_policies,
    }
