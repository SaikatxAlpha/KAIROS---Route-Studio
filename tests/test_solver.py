import numpy as np

from kairos.config import EVALUATION_SEED_OFFSET
from kairos.sim.montecarlo import RouteSpec, simulate
from kairos.solver.planners import (
    Candidate,
    PlannerConfig,
    buffered_inputs,
    plan,
    select_candidate,
    split_budget,
)
from kairos.solver.vrp import RoutingProblem, SolveResult, solve_problem
from kairos.uncertainty.stochastic import UncertaintyConfig


def _visits(sol):
    return [s for r in sol.routes for s in r.stops]


def test_solution_visits_each_client_once_and_respects_capacity(r101_small):
    sol = solve_problem(RoutingProblem.static(r101_small), iterations=800, seed=0)
    v = _visits(sol)
    assert sorted(v) == list(range(1, r101_small.n_nodes))
    for r in sol.routes:
        assert r101_small.demand[r.stops].sum() <= r101_small.capacity + 1e-9


def test_feasible_plan_meets_all_windows_nominally(r101_small):
    sol = solve_problem(RoutingProblem.static(r101_small), iterations=800, seed=0)
    assert sol.feasible and sol.time_warp == 0
    det = simulate(r101_small, [RouteSpec(r.stops, vehicle=i) for i, r in enumerate(sol.routes)],
                   UncertaintyConfig(), 1, 0, deterministic=True)
    assert det.metrics["on_time_rate"] == 1.0
    assert det.metrics["overtime_mean"] == 0.0
    # simulated nominal arrivals match the solver's schedule
    r = sol.routes[0]
    np.testing.assert_allclose(det.arrival[0, r.stops[0]], r101_small.travel_time[0, r.stops[0]], atol=0.1)


def test_solver_is_reproducible_for_a_seed(syn):
    a = solve_problem(RoutingProblem.static(syn), iterations=500, seed=7)
    b = solve_problem(RoutingProblem.static(syn), iterations=500, seed=7)
    assert [r.stops for r in a.routes] == [r.stops for r in b.routes]
    assert a.stop_reason == "iterations"


def test_fixed_cost_discourages_extra_vehicles(syn):
    from dataclasses import replace

    cheap = solve_problem(RoutingProblem.static(syn), iterations=800, seed=1)
    costly = solve_problem(RoutingProblem.static(replace(syn, vehicle_fixed_cost=1e4)), iterations=800, seed=1)
    assert len(costly.routes) <= len(cheap.routes)


def test_buffered_inputs_are_monotone(syn):
    cfg = UncertaintyConfig()
    t0, s0 = buffered_inputs(syn, cfg, 0.0)
    t1, s1 = buffered_inputs(syn, cfg, 1.0)
    t2, s2 = buffered_inputs(syn, cfg, 2.0)
    assert (t0 <= t1).all() and (t1 <= t2).all() and (s1 <= s2).all()
    np.testing.assert_array_equal(t0, syn.travel_time)


def test_split_budget():
    assert sum(split_budget(5000, 5, first_share=0.4)) == 5000
    assert split_budget(5000, 5, first_share=0.4)[0] == 2000
    assert sum(split_budget(1001, 4)) == 1001


def _cand(beta, dist, ot, unplanned=()):
    sol = SolveResult([], True, dist, dist, 0.0, 0, "iterations", unplanned=list(unplanned))
    return Candidate(beta, 0, sol, {"on_time_rate": ot})


def test_select_candidate_cheapest_meeting_target():
    cands = [_cand(0, 100, 0.90), _cand(0.5, 110, 0.96), _cand(1.0, 130, 0.99)]
    best, ok = select_candidate(cands, 0.95)
    assert ok and best.beta == 0.5
    best, ok = select_candidate(cands, 0.995)
    assert not ok and best.beta == 1.0  # most reliable fallback
    best, ok = select_candidate([_cand(0, 90, 0.99, unplanned=[3]), _cand(1, 120, 0.97)], 0.95)
    assert best.beta == 1  # candidates with unplanned stops are not eligible


def test_reliability_target_has_a_real_effect(c101_small):
    """Higher targets must not choose smaller buffers, and must change the plan
    on an instance where risk is material (C101: long service times)."""
    lo = plan(c101_small, PlannerConfig(method="reliability", target=0.8, iterations=1500, seed=0))
    hi = plan(c101_small, PlannerConfig(method="reliability", target=0.99, iterations=1500, seed=0))
    assert hi.beta >= lo.beta
    assert hi.beta > lo.beta or [r.stops for r in hi.routes] != [r.stops for r in lo.routes]
    cfg = UncertaintyConfig()
    ev_lo = simulate(c101_small, lo.routes, cfg, 300, EVALUATION_SEED_OFFSET).metrics
    ev_hi = simulate(c101_small, hi.routes, cfg, 300, EVALUATION_SEED_OFFSET).metrics
    assert ev_hi["on_time_rate"] >= ev_lo["on_time_rate"]
    assert ev_hi["distance"] >= ev_lo["distance"] - 1e-6


def test_reliability_beats_deterministic_out_of_sample(c101_small):
    det = plan(c101_small, PlannerConfig(method="deterministic", iterations=1500, seed=0))
    rel = plan(c101_small, PlannerConfig(method="reliability", target=0.95, iterations=1500, seed=0))
    cfg = UncertaintyConfig()
    a = simulate(c101_small, det.routes, cfg, 300, EVALUATION_SEED_OFFSET).metrics
    b = simulate(c101_small, rel.routes, cfg, 300, EVALUATION_SEED_OFFSET).metrics
    assert b["on_time_rate"] > a["on_time_rate"]
    assert len(rel.candidates) == 5 and sum(c.chosen for c in rel.candidates) == 1
