"""Vectorised Monte Carlo execution of route plans.

A plan is executed stop by stop under sampled realisations: the vehicle waits
if it arrives before a window opens, and a stop is *late* when the vehicle
arrives after the window closes (it is still served — lateness is measured,
not prevented). Returning after the depot closes is overtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kairos.data.schema import Instance
from kairos.uncertainty.stochastic import UncertaintyConfig, iter_scenarios

EPS = 1e-6


@dataclass
class RouteSpec:
    stops: list[int]  # node indices, in visiting order
    start_node: int = 0
    start_time: float | None = None  # None -> depot opening time
    vehicle: int = 0  # index into the vehicle-factor vector


@dataclass
class Effects:
    """Disruption effects applied to activity starting at or after ``start_time``."""

    start_time: float = 0.0
    travel_factor: np.ndarray | None = None  # (N, N)
    service_factor: np.ndarray | None = None  # (N,)
    end_time: float = np.inf

    def active(self, t: np.ndarray) -> np.ndarray:
        return (t >= self.start_time - EPS) & (t < self.end_time)


@dataclass
class SimulationResult:
    n_scenarios: int
    seed: int
    arrival: np.ndarray  # (S, N) NaN for unvisited nodes
    lateness: np.ndarray  # (S, N)
    route_end: np.ndarray  # (S, R)
    route_start: np.ndarray  # (R,)
    overtime: np.ndarray  # (S, R)
    tw_nodes: np.ndarray  # node indices whose windows are evaluated
    distance: float
    metrics: dict[str, Any] = field(default_factory=dict)


def plan_distance(inst: Instance, routes: list[RouteSpec]) -> float:
    total = 0.0
    for r in routes:
        if not r.stops:
            continue
        path = [r.start_node, *r.stops, 0]
        total += float(inst.distance[path[:-1], path[1:]].sum())
    return total


def simulate(
    inst: Instance,
    routes: list[RouteSpec],
    cfg: UncertaintyConfig,
    n_scenarios: int,
    seed: int,
    effects: Effects | None = None,
    deterministic: bool = False,
) -> SimulationResult:
    """Execute ``routes`` under ``n_scenarios`` sampled realisations.

    ``deterministic=True`` executes once on expected values (useful for
    checking a plan's nominal schedule).
    """
    n = inst.n_nodes
    if deterministic:
        n_scenarios = 1
    routes = [r for r in routes if r.stops]
    n_routes = len(routes)
    k_max = max([r.vehicle for r in routes], default=0) + 1

    arrival = np.full((n_scenarios, n), np.nan)
    route_end = np.zeros((n_scenarios, n_routes))
    starts = np.array(
        [inst.tw_early[0] if r.start_time is None else r.start_time for r in routes], dtype=float
    )

    tt = inst.travel_time
    svc = inst.service
    if deterministic:
        blocks = [None]
    else:
        blocks = iter_scenarios(inst, cfg, n_scenarios, seed, n_vehicles=max(k_max, inst.num_vehicles))

    for blk in blocks:
        if blk is None:
            s0, b = 0, 1
        else:
            s0, b = blk.start, len(blk.day)
        sl = slice(s0, s0 + b)
        for ri, r in enumerate(routes):
            t = np.full(b, starts[ri])
            prev = r.start_node
            for node in r.stops:
                travel = np.full(b, tt[prev, node])
                if blk is not None:
                    travel = travel * blk.day * blk.vehicle[:, r.vehicle] * blk.arc[:, prev, node]
                if effects is not None and effects.travel_factor is not None:
                    f = effects.travel_factor[prev, node]
                    travel = np.where(effects.active(t), travel * f, travel)
                t = t + travel
                arrival[sl, node] = t
                begin = np.maximum(t, inst.tw_early[node])
                service = np.full(b, svc[node]) if blk is None else svc[node] * blk.service[:, node]
                if effects is not None and effects.service_factor is not None:
                    f = effects.service_factor[node]
                    service = np.where(effects.active(begin), service * f, service)
                t = begin + service
                prev = node
            travel = np.full(b, tt[prev, 0])
            if blk is not None:
                travel = travel * blk.day * blk.vehicle[:, r.vehicle] * blk.arc[:, prev, 0]
            if effects is not None and effects.travel_factor is not None:
                travel = np.where(effects.active(t), travel * effects.travel_factor[prev, 0], travel)
            route_end[sl, ri] = t + travel

    lateness = np.where(np.isnan(arrival), 0.0, np.maximum(0.0, arrival - inst.tw_late[None, :]))
    overtime = np.maximum(0.0, route_end - inst.tw_late[0])
    visited = np.array(sorted({s for r in routes for s in r.stops}), dtype=int)
    tw_nodes = visited[inst.has_tw[visited]] if len(visited) else visited
    res = SimulationResult(
        n_scenarios=n_scenarios,
        seed=seed,
        arrival=arrival,
        lateness=lateness,
        route_end=route_end,
        route_start=starts,
        overtime=overtime,
        tw_nodes=tw_nodes,
        distance=plan_distance(inst, routes),
    )
    res.metrics = summarise(inst, res)
    return res


def summarise(inst: Instance, res: SimulationResult) -> dict[str, Any]:
    """Aggregate scenario-level outcomes into plan metrics."""
    tw = res.tw_nodes
    s = res.n_scenarios
    late = res.lateness[:, tw] > EPS if len(tw) else np.zeros((s, 0), dtype=bool)
    n_tw = max(len(tw), 1)
    on_time_per_scen = 1.0 - late.sum(1) / n_tw
    viol = late.sum(1)
    lateness_total = res.lateness[:, tw].sum(1) if len(tw) else np.zeros(s)
    durations = res.route_end - res.route_start[None, :]
    any_overtime = (res.overtime > EPS).any(1) if res.overtime.size else np.zeros(s, dtype=bool)
    se = float(on_time_per_scen.std(ddof=1) / np.sqrt(s)) if s > 1 else 0.0
    return {
        "n_scenarios": s,
        "n_routes": int(res.route_end.shape[1]),
        "n_stops": int((~np.isnan(res.arrival[0])).sum()),
        "n_window_stops": int(len(tw)),
        "distance": res.distance,
        "on_time_rate": float(on_time_per_scen.mean()),
        "on_time_rate_se": se,
        "p_all_on_time": float((viol == 0).mean()),
        "violations_mean": float(viol.mean()),
        "lateness_total_mean": float(lateness_total.mean()),
        "lateness_total_p90": float(np.quantile(lateness_total, 0.9)),
        "lateness_per_late_stop": float(lateness_total.sum() / max(viol.sum(), 1)),
        "overtime_mean": float(res.overtime.sum(1).mean()) if res.overtime.size else 0.0,
        "p_overtime": float(any_overtime.mean()),
        "duration_total_mean": float(durations.sum(1).mean()) if durations.size else 0.0,
        "makespan_mean": float(res.route_end.max(1).mean()) if res.route_end.size else 0.0,
    }


def stop_profiles(inst: Instance, res: SimulationResult, quantiles=(0.1, 0.5, 0.9)) -> list[dict[str, Any]]:
    """Per-stop arrival distribution and on-time probability (for the UI)."""
    out = []
    visited = np.flatnonzero(~np.isnan(res.arrival[0]))
    q = np.quantile(res.arrival[:, visited], quantiles, axis=0) if len(visited) else np.zeros((3, 0))
    p_late = (res.lateness[:, visited] > EPS).mean(0) if len(visited) else []
    mean_late = res.lateness[:, visited].mean(0) if len(visited) else []
    for j, node in enumerate(visited):
        out.append(
            {
                "node": int(node),
                "arrival_p10": float(q[0, j]),
                "arrival_p50": float(q[1, j]),
                "arrival_p90": float(q[2, j]),
                "p_late": float(p_late[j]) if inst.has_tw[node] else 0.0,
                "mean_lateness": float(mean_late[j]),
            }
        )
    return out
