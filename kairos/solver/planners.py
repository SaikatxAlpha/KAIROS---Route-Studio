"""Planning policies compared in KAIROS.

``deterministic``  PyVRP on expected travel/service times (the baseline).
``buffered``       PyVRP on quantile-style buffered times
                   (t + z_alpha * sd), a single solve. Ablation: buffer only.
``saa_select``     Several deterministic solves (different seeds) and
                   scenario-based selection. Ablation: selection only.
``reliability``    The proposed planner. Generates a ladder of candidate
                   plans with increasing safety buffers (warm-started along the
                   ladder), estimates each candidate's on-time rate on
                   *in-sample* planning scenarios (sample average
                   approximation of a chance constraint), and returns the
                   cheapest candidate whose estimated on-time rate meets the
                   reliability target. If none does, it returns the most
                   reliable candidate and flags the target as unattained.

All policies share one search budget (PyVRP iterations); multi-candidate
policies split it across candidates (the reliability planner gives 40% to the
unbuffered candidate and warm-starts the rest along the ladder), so
comparisons are at equal computational budget. Out-of-sample evaluation always uses a disjoint
scenario stream (see ``kairos.config`` seed offsets).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any, Callable

import numpy as np

from kairos.config import PLANNING_SEED_OFFSET
from kairos.data.schema import Instance
from kairos.sim.montecarlo import RouteSpec, simulate
from kairos.solver.vrp import RoutingProblem, SolveResult, solve_problem
from kairos.uncertainty.stochastic import UncertaintyConfig, service_sd, travel_sd

METHODS = ("deterministic", "buffered", "saa_select", "reliability")
DEFAULT_LADDER = (0.0, 0.5, 1.0, 1.5, 2.0)
FIRST_SHARE = 0.4  # share of the budget for the unbuffered (beta = 0) candidate


def split_budget(total: int, n: int, first_share: float | None = None) -> list[int]:
    """Split an iteration budget over ``n`` candidates (sums to ``total``).

    With ``first_share`` the first candidate receives that fraction and the
    rest share the remainder; later candidates are warm-started, so they need
    fewer iterations to converge."""
    if n == 1:
        return [total]
    if first_share is None:
        base = [total // n] * n
    else:
        first = int(round(total * first_share))
        rest = total - first
        base = [first] + [rest // (n - 1)] * (n - 1)
    base[-1] += total - sum(base)
    return [max(50, b) for b in base]


@dataclass
class PlannerConfig:
    method: str = "reliability"
    target: float = 0.95  # reliability target: expected share of window stops served on time
    iterations: int = 5000  # total PyVRP iteration budget
    time_limit: float = 10.0  # wall-clock safety cap per solve (s)
    seed: int = 0
    planning_scenarios: int = 100
    ladder: tuple[float, ...] = DEFAULT_LADDER
    uncertainty: UncertaintyConfig = field(default_factory=UncertaintyConfig)

    def validate(self) -> None:
        if self.method not in METHODS:
            raise ValueError(f"unknown method {self.method!r}; choose one of {METHODS}")
        if not 0.5 <= self.target <= 0.999:
            raise ValueError("target must lie in [0.5, 0.999]")
        if self.iterations < 50:
            raise ValueError("iteration budget must be at least 50")
        if self.planning_scenarios < 10:
            raise ValueError("at least 10 planning scenarios are required")
        if not self.ladder or any(b < 0 for b in self.ladder):
            raise ValueError("ladder must contain non-negative buffer levels")

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "target": self.target,
            "iterations": self.iterations,
            "time_limit": self.time_limit,
            "seed": self.seed,
            "planning_scenarios": self.planning_scenarios,
            "ladder": list(self.ladder),
            "uncertainty": self.uncertainty.to_dict(),
        }


@dataclass
class Candidate:
    beta: float
    seed: int
    solve: SolveResult
    in_sample: dict[str, Any]
    chosen: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "beta": self.beta,
            "seed": self.seed,
            "distance": self.solve.distance,
            "n_routes": len(self.solve.routes),
            "planned_feasible": self.solve.feasible,
            "time_warp": self.solve.time_warp,
            "runtime_s": self.solve.runtime,
            "in_sample_on_time_rate": self.in_sample.get("on_time_rate"),
            "in_sample_p_all_on_time": self.in_sample.get("p_all_on_time"),
            "in_sample_lateness": self.in_sample.get("lateness_total_mean"),
            "chosen": self.chosen,
        }


@dataclass
class Plan:
    instance_id: str
    method: str
    config: PlannerConfig
    routes: list[RouteSpec]
    solve: SolveResult
    beta: float
    candidates: list[Candidate] = field(default_factory=list)
    target_attained: bool | None = None
    runtime_total: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "method": self.method,
            "config": self.config.to_dict(),
            "beta": self.beta,
            "solver": self.solve.to_dict(),
            "runtime_total_s": self.runtime_total,
            "target_attained": self.target_attained,
            "candidates": [c.to_dict() for c in self.candidates],
            "routes": [
                {
                    "vehicle": r.vehicle,
                    "stops": r.stops,
                    "planned_arrival": pr.planned_arrival,
                    "planned_start": pr.planned_start,
                    "planned_end": pr.planned_end,
                    "distance": pr.distance,
                }
                for r, pr in zip(self.routes, self.solve.routes)
            ],
        }


def buffered_inputs(inst: Instance, cfg: UncertaintyConfig, beta: float) -> tuple[np.ndarray, np.ndarray]:
    """Planning durations ``mean + beta * sd`` for travel and service."""
    if beta == 0:
        return inst.travel_time, inst.service
    return inst.travel_time + beta * travel_sd(inst, cfg), inst.service + beta * service_sd(inst, cfg)


def routes_from_solve(sol: SolveResult) -> list[RouteSpec]:
    return [RouteSpec(stops=list(r.stops), vehicle=i) for i, r in enumerate(sol.routes)]


ProgressFn = Callable[[float, str], None]


def _solve_beta(inst, pc, beta, iterations, seed, init=None) -> SolveResult:
    dur, svc = buffered_inputs(inst, pc.uncertainty, beta)
    prob = RoutingProblem.static(inst, duration=dur, service=svc)
    return solve_problem(prob, iterations=iterations, time_limit=pc.time_limit, seed=seed, initial_routes=init)


def _in_sample(inst: Instance, pc: PlannerConfig, sol: SolveResult) -> dict[str, Any]:
    res = simulate(
        inst, routes_from_solve(sol), pc.uncertainty, pc.planning_scenarios, pc.seed + PLANNING_SEED_OFFSET
    )
    return res.metrics


def select_candidate(cands: list[Candidate], target: float) -> tuple[Candidate, bool]:
    """Cheapest candidate meeting the target; otherwise the most reliable one."""
    ok = [c for c in cands if c.in_sample["on_time_rate"] >= target and not c.solve.unplanned]
    if ok:
        return min(ok, key=lambda c: (c.solve.distance, -c.in_sample["on_time_rate"])), True
    return max(cands, key=lambda c: (c.in_sample["on_time_rate"], -c.solve.distance)), False


def plan(inst: Instance, pc: PlannerConfig, progress: ProgressFn | None = None) -> Plan:
    pc.validate()
    t0 = time.perf_counter()
    report = progress or (lambda f, m: None)

    if pc.method == "deterministic":
        report(0.1, "Solving deterministic VRPTW")
        sol = _solve_beta(inst, pc, 0.0, pc.iterations, pc.seed)
        p = Plan(inst.id, pc.method, pc, routes_from_solve(sol), sol, beta=0.0)
    elif pc.method == "buffered":
        beta = NormalDist().inv_cdf(pc.target)
        report(0.1, f"Solving buffered VRPTW (beta={beta:.2f})")
        sol = _solve_beta(inst, pc, beta, pc.iterations, pc.seed)
        p = Plan(inst.id, pc.method, pc, routes_from_solve(sol), sol, beta=beta)
    else:
        if pc.method == "saa_select":
            specs = [(0.0, pc.seed + i) for i in range(len(pc.ladder))]
        else:
            specs = [(b, pc.seed) for b in sorted(pc.ladder)]
        budgets = split_budget(pc.iterations, len(specs), first_share=FIRST_SHARE if pc.method == "reliability" else None)
        cands: list[Candidate] = []
        prev_routes = None
        for i, (beta, seed) in enumerate(specs):
            report(0.05 + 0.9 * i / len(specs), f"Candidate {i + 1}/{len(specs)} (buffer {beta:.2f})")
            init = prev_routes if pc.method == "reliability" else None
            sol = _solve_beta(inst, pc, beta, budgets[i], seed, init=init)
            prev_routes = [r.stops for r in sol.routes]
            cands.append(Candidate(beta, seed, sol, _in_sample(inst, pc, sol)))
        best, attained = select_candidate(cands, pc.target)
        best.chosen = True
        p = Plan(
            inst.id,
            pc.method,
            pc,
            routes_from_solve(best.solve),
            best.solve,
            beta=best.beta,
            candidates=cands,
            target_attained=attained,
        )
    p.runtime_total = time.perf_counter() - t0
    report(1.0, "Plan ready")
    return p
