"""Thin, typed adapter around PyVRP (verified against PyVRP 0.14).

The adapter builds ``pyvrp.ProblemData`` directly from numpy matrices, which
is far faster than adding edges one at a time, and maps solutions back to the
instance's node indices. It supports the features KAIROS needs for static
planning *and* mid-day replanning:

* hard time windows, service durations, capacity;
* several depots (vehicles can start at their current position after a
  disruption and must return to the main depot);
* per-vehicle-type shift windows and fixed dispatch costs.

Search is stopped by an iteration budget (deterministic for a given seed) with
a wall-clock safety cap; the result records which criterion fired.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pyvrp import Client, Depot, Location, ProblemData, Solution, VehicleType, solve
from pyvrp.stop import MaxIterations, MaxRuntime, MultipleCriteria

from kairos.data.schema import Instance

BIG = np.iinfo(np.int64).max // 4


@dataclass
class DepotSpec:
    node: int  # instance node index providing the location
    tw_early: float = 0.0
    tw_late: float = float("inf")


@dataclass
class VehicleSpec:
    start_depot: int  # index into the problem's depot list
    end_depot: int = 0
    num_available: int = 1
    tw_early: float = 0.0
    tw_late: float = float("inf")
    capacity: float | None = None
    fixed_cost: float = 0.0
    name: str = ""


@dataclass
class RoutingProblem:
    """A (sub)problem over a subset of instance nodes."""

    inst: Instance
    clients: list[int]  # instance node indices to visit
    depots: list[DepotSpec]
    vehicles: list[VehicleSpec]
    duration: np.ndarray  # (N, N) planning travel times (may be buffered)
    service: np.ndarray  # (N,) planning service durations
    tw_late: np.ndarray | None = None  # optional override of latest service start

    @classmethod
    def static(
        cls,
        inst: Instance,
        duration: np.ndarray | None = None,
        service: np.ndarray | None = None,
        num_vehicles: int | None = None,
    ) -> "RoutingProblem":
        return cls(
            inst=inst,
            clients=list(range(1, inst.n_nodes)),
            depots=[DepotSpec(0, inst.tw_early[0], inst.tw_late[0])],
            vehicles=[
                VehicleSpec(
                    start_depot=0,
                    end_depot=0,
                    num_available=num_vehicles or inst.num_vehicles,
                    tw_early=inst.tw_early[0],
                    tw_late=inst.tw_late[0],
                    capacity=inst.capacity,
                    fixed_cost=inst.vehicle_fixed_cost,
                    name="fleet",
                )
            ],
            duration=inst.travel_time if duration is None else duration,
            service=inst.service if service is None else service,
        )


@dataclass
class PlannedRoute:
    vehicle_type: int
    start_depot: int  # index into RoutingProblem.depots
    stops: list[int]  # instance node indices
    planned_start: float
    planned_arrival: list[float]
    planned_end: float
    distance: float
    time_warp: float


@dataclass
class SolveResult:
    routes: list[PlannedRoute]
    feasible: bool
    objective: float
    distance: float
    runtime: float
    iterations: int
    stop_reason: str
    unplanned: list[int] = field(default_factory=list)
    time_warp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "feasible": self.feasible,
            "objective": self.objective,
            "distance": self.distance,
            "runtime_s": self.runtime,
            "iterations": self.iterations,
            "stop_reason": self.stop_reason,
            "unplanned": self.unplanned,
            "time_warp": self.time_warp,
            "n_routes": len(self.routes),
        }


def _to_int(x: np.ndarray | float, scale: float, mode: str = "round") -> np.ndarray:
    """Scale to integers. Durations use ``ceil`` and latest times ``floor`` so
    that a plan feasible in PyVRP's integer arithmetic is also feasible in the
    continuous-time simulator (conservative rounding)."""
    arr = np.asarray(x, dtype=float) * scale
    arr = np.where(np.isfinite(arr), np.minimum(arr, BIG), BIG)
    f = {"round": np.rint, "ceil": lambda a: np.ceil(a - 1e-9), "floor": lambda a: np.floor(a + 1e-9)}[mode]
    return f(arr).astype(np.int64)


def build_problem_data(prob: RoutingProblem) -> tuple[ProblemData, list[int]]:
    """Return PyVRP data plus the location -> instance-node mapping."""
    inst = prob.inst
    sc = inst.int_scale
    loc_nodes = [d.node for d in prob.depots] + list(prob.clients)
    coords = inst.coords[loc_nodes]
    locations = [Location(float(x), float(y)) for x, y in coords]
    idx = np.asarray(loc_nodes)
    dist = _to_int(inst.distance[np.ix_(idx, idx)], sc)
    dur = _to_int(prob.duration[np.ix_(idx, idx)], sc, "ceil")
    np.fill_diagonal(dist, 0)
    np.fill_diagonal(dur, 0)

    depots = [
        Depot(
            location=i,
            tw_early=int(_to_int(d.tw_early, sc, "ceil")),
            tw_late=int(_to_int(d.tw_late, sc, "floor")),
        )
        for i, d in enumerate(prob.depots)
    ]
    tw_late = inst.tw_late if prob.tw_late is None else prob.tw_late
    demand_scale = 1.0 if float(inst.demand.max(initial=0)).is_integer() else 1000.0
    clients = []
    for j, node in enumerate(prob.clients):
        clients.append(
            Client(
                location=len(prob.depots) + j,
                delivery=[int(round(inst.demand[node] * demand_scale))],
                service_duration=int(_to_int(prob.service[node], sc, "ceil")),
                tw_early=int(_to_int(inst.tw_early[node], sc, "ceil")),
                tw_late=int(_to_int(tw_late[node], sc, "floor")),
                name=inst.stop_ids[node],
            )
        )
    vtypes = []
    for v in prob.vehicles:
        cap = inst.capacity if v.capacity is None else v.capacity
        vtypes.append(
            VehicleType(
                num_available=v.num_available,
                capacity=[int(np.floor(cap * demand_scale + 1e-9))],
                start_depot=v.start_depot,
                end_depot=v.end_depot,
                fixed_cost=int(_to_int(v.fixed_cost, sc)),
                tw_early=int(_to_int(v.tw_early, sc, "ceil")),
                tw_late=int(_to_int(v.tw_late, sc, "floor")),
                name=v.name,
            )
        )
    data = ProblemData(
        locations=locations,
        clients=clients,
        depots=depots,
        vehicle_types=vtypes,
        distance_matrices=[dist],
        duration_matrices=[dur],
    )
    return data, loc_nodes


def solve_problem(
    prob: RoutingProblem,
    iterations: int = 2000,
    time_limit: float = 5.0,
    seed: int = 0,
    initial_routes: list[list[int]] | None = None,
) -> SolveResult:
    if not prob.clients:
        return SolveResult([], True, 0.0, 0.0, 0.0, 0, "empty")
    data, loc_nodes = build_problem_data(prob)
    sc = prob.inst.int_scale
    stop = MultipleCriteria([MaxIterations(iterations), MaxRuntime(time_limit)])
    init = None
    if initial_routes:
        node_to_client = {node: j for j, node in enumerate(prob.clients)}
        init_routes = [[node_to_client[n] for n in r if n in node_to_client] for r in initial_routes]
        init_routes = [r for r in init_routes if r]
        try:
            init = Solution(data, init_routes)
        except RuntimeError:
            init = None
    t0 = time.perf_counter()
    res = solve(data, stop, seed=seed, collect_stats=False, display=False, initial_solution=init)
    runtime = time.perf_counter() - t0
    best = res.best
    n_dep = len(prob.depots)
    routes: list[PlannedRoute] = []
    for r in best.routes():
        stops, arrivals = [], []
        start = end = 0.0
        for act in r.schedule():
            if act.type.name == "CLIENT":
                stops.append(loc_nodes[n_dep + act.idx])
                arrivals.append(act.start_time / sc)
        start = r.start_time() / sc
        end = r.end_time() / sc
        routes.append(
            PlannedRoute(
                vehicle_type=r.vehicle_type(),
                start_depot=r.start_depot(),
                stops=stops,
                planned_start=start,
                planned_arrival=arrivals,
                planned_end=end,
                distance=r.distance() / sc,
                time_warp=r.time_warp() / sc,
            )
        )
    visited = {s for r in routes for s in r.stops}
    stop_reason = "time_limit" if runtime >= time_limit * 0.98 else "iterations"
    return SolveResult(
        routes=routes,
        feasible=bool(best.is_feasible()),
        objective=float(res.cost()) / sc if np.isfinite(res.cost()) else float("inf"),
        distance=best.distance() / sc,
        runtime=runtime,
        iterations=int(res.num_iterations),
        stop_reason=stop_reason,
        unplanned=[c for c in prob.clients if c not in visited],
        time_warp=best.time_warp() / sc,
    )
