import numpy as np
import pytest

from kairos.data.schema import Instance
from kairos.sim.montecarlo import Effects, RouteSpec, simulate, stop_profiles
from kairos.uncertainty.stochastic import UncertaintyConfig, iter_scenarios, travel_sd


def _line_instance():
    # depot at 0, stops at 10 and 20 on a line; windows make stop 2 tight
    coords = np.array([[0.0, 0], [10, 0], [20, 0]])
    d = np.abs(coords[:, None, 0] - coords[None, :, 0])
    return Instance(
        id="line", name="line", source="synthetic", coord_system="euclidean", coords=coords,
        travel_time=d, distance=d, service=np.array([0, 5.0, 5.0]),
        tw_early=np.array([0, 0, 0.0]), tw_late=np.array([100, 50, 36.0]),
        demand=np.array([0, 1, 1.0]), capacity=10, num_vehicles=2,
    )


def test_deterministic_execution_and_lateness():
    inst = _line_instance()
    res = simulate(inst, [RouteSpec([1, 2])], UncertaintyConfig(), 1, 0, deterministic=True)
    # arrive 1 at 10, leave 15, arrive 2 at 25 (on time, window closes 36)
    assert res.arrival[0, 1] == 10 and res.arrival[0, 2] == 25
    assert res.metrics["on_time_rate"] == 1.0
    # reverse order: arrive 2 at 20, leave 25, arrive 1 at 35, leave 40, return at 50
    res = simulate(inst, [RouteSpec([2, 1])], UncertaintyConfig(), 1, 0, deterministic=True)
    assert res.route_end[0, 0] == 50
    # make stop 2 late: start the route at t=20
    res = simulate(inst, [RouteSpec([1, 2], start_time=20)], UncertaintyConfig(), 1, 0, deterministic=True)
    assert res.lateness[0, 2] == pytest.approx(9.0)
    assert res.metrics["on_time_rate"] == 0.5 and res.metrics["violations_mean"] == 1


def test_scenarios_are_reproducible_and_common(syn):
    cfg = UncertaintyConfig()
    a = list(iter_scenarios(syn, cfg, 60, seed=11))
    b = list(iter_scenarios(syn, cfg, 60, seed=11))
    np.testing.assert_array_equal(a[1].arc, b[1].arc)
    # fleet size does not perturb any other component (common random numbers)
    c = list(iter_scenarios(syn, cfg, 60, seed=11, n_vehicles=9))
    np.testing.assert_array_equal(a[0].arc, c[0].arc)
    np.testing.assert_array_equal(a[0].day, c[0].day)
    np.testing.assert_array_equal(a[0].vehicle[:, :3], c[0].vehicle[:, :3])
    d = list(iter_scenarios(syn, cfg, 60, seed=12))
    assert not np.array_equal(a[0].arc, d[0].arc)


def test_multipliers_have_unit_mean(syn):
    cfg = UncertaintyConfig()
    arcs = np.concatenate([b.arc[:, 1:, 2:].ravel() for b in iter_scenarios(syn, cfg, 400, seed=1)])
    assert abs(arcs.mean() - 1.0) < 0.01
    svc = np.concatenate([b.service.ravel() for b in iter_scenarios(syn, cfg, 400, seed=1)])
    assert abs(svc.mean() - 1.0) < 0.02


def test_travel_sd_matches_simulation(syn):
    cfg = UncertaintyConfig()
    i, j = 1, 2
    samples = []
    for b in iter_scenarios(syn, cfg, 2000, seed=5):
        samples.append(syn.travel_time[i, j] * b.day * b.vehicle[:, 0] * b.arc[:, i, j])
    s = np.concatenate(samples)
    assert s.std() == pytest.approx(travel_sd(syn, cfg)[i, j], rel=0.08)


def test_simulation_reproducible_and_effects_slow_down(syn):
    routes = [RouteSpec(list(range(1, 11)), vehicle=0), RouteSpec(list(range(11, 21)), vehicle=1)]
    cfg = UncertaintyConfig()
    a = simulate(syn, routes, cfg, 100, seed=3)
    b = simulate(syn, routes, cfg, 100, seed=3)
    assert a.metrics == b.metrics
    eff = Effects(start_time=0.0, travel_factor=np.full((syn.n_nodes,) * 2, 2.0))
    slow = simulate(syn, routes, cfg, 100, seed=3, effects=eff)
    assert slow.metrics["makespan_mean"] > a.metrics["makespan_mean"]
    assert slow.metrics["on_time_rate"] <= a.metrics["on_time_rate"]
    prof = stop_profiles(syn, a)
    assert len(prof) == 20
    assert all(p["arrival_p10"] <= p["arrival_p50"] <= p["arrival_p90"] for p in prof)
