import numpy as np
import pytest

from kairos.sim.dynamic import (
    DisruptionEvent,
    apply_event,
    diff_plans,
    hold_policy,
    observe_state,
    run_disruption,
)
from kairos.solver.planners import PlannerConfig, plan
from kairos.uncertainty.stochastic import UncertaintyConfig


@pytest.fixture(scope="module")
def base(r101_small):
    p = plan(r101_small, PlannerConfig(method="deterministic", iterations=800, seed=0))
    return r101_small, p.routes


def _all_stops(out, policy):
    return sorted(s for r in out["policies"][policy]["routes"] for s in r["stops"])


def test_observe_state_partitions_stops(base):
    inst, routes = base
    state, arrivals = observe_state(inst, routes, 60.0, UncertaintyConfig(), world_seed=1)
    seen = []
    for v in state.vehicles:
        seen += v.completed + ([v.committed] if v.committed is not None else []) + v.remaining
        assert v.available_at >= 60.0 - 1e-9 or v.status == "returned"
    assert sorted(seen) == list(range(1, inst.n_nodes))
    assert np.isfinite(arrivals).sum() >= sum(len(v.completed) for v in state.vehicles)


def test_breakdown_reassigns_orphaned_stops(base):
    inst, routes = base
    ev = DisruptionEvent("breakdown", 60.0, vehicle=1)
    out = run_disruption(inst, routes, ev, UncertaintyConfig(), iterations=600, seed=0, eval_scenarios=50,
                         planning_scenarios=20)
    broken = next(v for v in out["state"]["vehicles"] if v["route_index"] == 1)
    assert broken["status"] == "broken"
    orphans = ([broken["committed"]] if broken["committed"] is not None else []) + broken["remaining"]
    done = {s for v in out["state"]["vehicles"] for s in v["completed"]}
    committed = {v["committed"] for v in out["state"]["vehicles"] if v["committed"] is not None and v["route_index"] != 1}
    expected = sorted(set(range(1, inst.n_nodes)) - done - committed)
    for pol in ("hold", "reoptimise", "reliability"):
        assert _all_stops(out, pol) == expected, pol
        assert all(r["vehicle"] != 1 for r in out["policies"][pol]["routes"])
        moved = {m["stop"] for m in out["policies"][pol]["diff"]["moved"]}
        assert set(orphans) <= moved


def test_urgent_order_is_served_exactly_once(base):
    inst, routes = base
    ev = DisruptionEvent("urgent_order", 50.0, location=(40.0, 40.0), window=60.0, service=10.0, demand=5.0)
    out = run_disruption(inst, routes, ev, UncertaintyConfig(), iterations=600, seed=0, eval_scenarios=50,
                         planning_scenarios=20)
    k = out["new_node"]
    assert k == inst.n_nodes
    for pol in out["policies"]:
        assert _all_stops(out, pol).count(k) == 1


def test_traffic_and_service_events_change_inputs(base):
    inst, _ = base
    w = apply_event(inst, DisruptionEvent("traffic", 30.0, factor=2.0, center=(35.0, 35.0), radius=15.0))
    assert w.planning_travel.max() > inst.travel_time.max() or (w.planning_travel >= inst.travel_time).all()
    assert len(w.affected_nodes) > 0
    i = w.affected_nodes[0]
    assert w.planning_travel[0, i] == pytest.approx(2 * inst.travel_time[0, i])
    s = apply_event(inst, DisruptionEvent("service_shock", 30.0, factor=3.0))
    np.testing.assert_allclose(s.planning_service, 3 * inst.service)
    with pytest.raises(ValueError):
        apply_event(inst, DisruptionEvent("weather", 1e9))
    with pytest.raises(ValueError):
        apply_event(inst, DisruptionEvent("urgent_order", 10.0))


def test_disruption_is_reproducible(base):
    inst, routes = base
    ev = DisruptionEvent("weather", 70.0, factor=1.3)
    kw = dict(iterations=400, seed=2, eval_scenarios=40, planning_scenarios=20, policies=("hold", "reoptimise"))
    a = run_disruption(inst, routes, ev, UncertaintyConfig(), **kw)
    b = run_disruption(inst, routes, ev, UncertaintyConfig(), **kw)
    for p in ("hold", "reoptimise"):
        assert a["policies"][p]["routes"] == b["policies"][p]["routes"]
        assert a["policies"][p]["metrics"]["on_time_rate"] == b["policies"][p]["metrics"]["on_time_rate"]


def test_hold_policy_keeps_sequences_without_event_changes(base):
    inst, routes = base
    state, _ = observe_state(inst, routes, 60.0, UncertaintyConfig(), world_seed=1)
    w = apply_event(inst, DisruptionEvent("weather", 60.0, factor=1.0))
    rp = hold_policy(w, state)
    before = {v.route_index: v.remaining for v in state.vehicles if v.remaining}
    after = dict(zip(rp.vehicle_labels, [r.stops for r in rp.routes]))
    assert diff_plans(before, after)["n_moved"] == 0


def test_diff_plans():
    d = diff_plans({0: [1, 2, 3], 1: [4, 5]}, {0: [2, 1], 1: [4, 5, 3]})
    assert d["n_moved"] == 1 and d["moved"][0] == {"stop": 3, "from": 0, "to": 1}
    assert d["resequenced_vehicles"] == [0]
