import math

import numpy as np
import pytest

from kairos.data.amazon import (
    AmazonSchemaError,
    MergeConfig,
    build_bundle,
    date_split,
    expected_schedule,
    merge_routes,
)
from kairos.data.registry import load_instance, read_instance, save_instance
from kairos.data.schema import Instance, InstanceValidationError
from kairos.data.solomon import SolomonParseError, list_solomon, load_solomon, parse_solomon, subsample
from kairos.data.synthetic import make_synthetic


def test_all_56_solomon_instances_parse():
    names = list_solomon()
    assert len(names) == 56
    for n in names:
        inst = load_solomon(n)
        assert inst.n_clients == 100
        assert inst.num_vehicles == 25
        assert (inst.tw_early <= inst.tw_late).all()


def test_solomon_r101_values():
    inst = load_solomon("R101")
    assert inst.capacity == 200
    assert inst.demand.sum() == 1458
    assert inst.tw_late[0] == 230
    assert inst.meta["group"] == "R1" and inst.meta["tight_windows"]
    np.testing.assert_allclose(inst.travel_time, inst.travel_time.T)
    assert inst.travel_time[0, 1] == pytest.approx(math.hypot(41 - 35, 49 - 35))


def test_solomon_parse_errors():
    with pytest.raises(SolomonParseError):
        parse_solomon("garbage", "X1")
    with pytest.raises(FileNotFoundError):
        load_solomon("Z999")


def _tiny(**over):
    base = dict(
        id="t", name="t", source="synthetic", coord_system="euclidean",
        coords=np.array([[0, 0], [1, 0], [0, 1]]), travel_time=np.ones((3, 3)) - np.eye(3),
        distance=np.ones((3, 3)) - np.eye(3), service=np.zeros(3), tw_early=np.zeros(3),
        tw_late=np.array([10.0, 5, 5]), demand=np.array([0, 1, 1.0]), capacity=5, num_vehicles=1,
    )
    base.update(over)
    return Instance(**base)


@pytest.mark.parametrize(
    "over,msg",
    [
        ({"tw_early": np.array([0, 6.0, 0])}, "tw_early > tw_late"),
        ({"travel_time": -np.ones((3, 3))}, "negative"),
        ({"demand": np.array([0, 9.0, 1])}, "exceeds vehicle capacity"),
        ({"travel_time": np.full((3, 3), np.nan)}, "non-finite"),
        ({"service": np.zeros(2)}, "length"),
        ({"coord_system": "polar"}, "coord_system"),
    ],
)
def test_schema_validation_rejects_bad_instances(over, msg):
    with pytest.raises(InstanceValidationError, match=msg):
        _tiny(**over)


def test_subsample_and_synthetic_are_deterministic():
    a, b = subsample(load_solomon("RC101"), 20, seed=4), subsample(load_solomon("RC101"), 20, seed=4)
    np.testing.assert_array_equal(a.coords, b.coords)
    s1, s2 = make_synthetic(30, 4, 9), make_synthetic(30, 4, 9)
    np.testing.assert_array_equal(s1.tw_late, s2.tw_late)
    assert s1.source == "synthetic"


def test_registry_roundtrip(tmp_path, syn):
    p = save_instance(syn, tmp_path / "x.json.gz")
    back = read_instance(p)
    np.testing.assert_allclose(back.travel_time, syn.travel_time, atol=0.05)
    assert back.id == syn.id and back.num_vehicles == syn.num_vehicles
    assert load_instance("solomon/C101").n_clients == 100
    with pytest.raises(KeyError):
        load_instance("nope/1")


# --- Amazon ingestion -------------------------------------------------------


def _route():
    stops = {
        "ST": {"lat": 34.0, "lng": -118.0, "type": "Station", "zone_id": float("nan")},
        "AA": {"lat": 34.01, "lng": -118.01, "type": "Dropoff", "zone_id": "A-1.1A"},
        "BB": {"lat": 34.02, "lng": -118.0, "type": "Dropoff", "zone_id": "A-1.2B"},
        "CC": {"lat": 34.0, "lng": -118.02, "type": "Dropoff", "zone_id": None},
    }
    route = {"station_code": "DLA1", "date_YYYY_MM_DD": "2018-07-20", "departure_time_utc": "15:00:00",
             "executor_capacity_cm3": 3_000_000.0, "route_score": "High", "stops": stops}
    ids = list(stops)
    matrix = {a: {b: (0.0 if a == b else 100.0 + 10 * i + j) for j, b in enumerate(ids)} for i, a in enumerate(ids)}
    nanw = {"start_time_utc": float("nan"), "end_time_utc": float("nan")}
    packages = {
        "AA": {"P1": {"scan_status": "DELIVERED", "time_window": nanw, "planned_service_time_seconds": 60.0,
                      "dimensions": {"depth_cm": 10.0, "height_cm": 10.0, "width_cm": 10.0}}},
        "BB": {
            "P2": {"scan_status": "DELIVERED", "planned_service_time_seconds": 30.0,
                   "time_window": {"start_time_utc": "2018-07-20 16:00:00", "end_time_utc": "2018-07-20 20:00:00"},
                   "dimensions": {"depth_cm": 20.0, "height_cm": 10.0, "width_cm": 10.0}},
            "P3": {"scan_status": "DELIVERED", "planned_service_time_seconds": 40.0,
                   "time_window": {"start_time_utc": "2018-07-20 17:00:00", "end_time_utc": "2018-07-20 21:00:00"},
                   "dimensions": {"depth_cm": float("nan"), "height_cm": 1.0, "width_cm": 1.0}},
        },
        "CC": {"P4": {"scan_status": "DELIVERED", "time_window": nanw, "planned_service_time_seconds": 50.0,
                      "dimensions": {"depth_cm": 5.0, "height_cm": 5.0, "width_cm": 5.0}}},
    }
    actual = {"actual": {"ST": 0, "CC": 1, "AA": 2, "BB": 3}}
    return route, packages, matrix, actual


def test_build_bundle_validates_and_converts():
    route, packages, matrix, actual = _route()
    b = build_bundle("RouteID_x", route, packages, matrix, actual)
    assert b.stop_ids[0] == "ST" and len(b.stop_ids) == 4
    assert b.departure_s == 15 * 3600
    i_bb = b.stop_ids.index("BB")
    assert b.service_s[i_bb] == 70.0  # summed over packages
    # window intersection: [17:00, 20:00]
    assert b.tw_start_s[i_bb] == 17 * 3600 and b.tw_end_s[i_bb] == 20 * 3600
    assert np.isnan(b.tw_start_s[b.stop_ids.index("AA")])
    assert b.zones[b.stop_ids.index("CC")] is None  # null zone kept as missing
    assert b.volume_l[i_bb] == pytest.approx(2.0)  # NaN dimension package skipped
    assert [b.stop_ids[i] for i in b.actual_order] == ["ST", "CC", "AA", "BB"]
    eta = expected_schedule(b)
    assert eta[b.stop_ids.index("CC")] < eta[b.stop_ids.index("AA")] < eta[i_bb]


def test_build_bundle_rejects_incomplete_matrix():
    route, packages, matrix, actual = _route()
    del matrix["AA"]
    with pytest.raises(AmazonSchemaError, match="missing from travel matrix"):
        build_bundle("RouteID_x", route, packages, matrix, actual)


def test_date_split_is_chronological():
    dates = [f"2018-07-{d:02d}" for d in range(1, 21)]
    s = date_split(dates)
    order = [s[d] for d in sorted(dates)]
    assert order == sorted(order, key=["train", "calibration", "test"].index)
    assert order.count("train") == 14 and order.count("test") == 3


def test_merge_routes_labels_observed_estimated_synthetic():
    route, packages, matrix, actual = _route()
    b1 = build_bundle("RouteID_a", route, packages, matrix, actual)
    route2 = {**route, "departure_time_utc": "15:10:00"}
    b2 = build_bundle("RouteID_b", route2, packages, matrix, actual)
    b2.lat = b2.lat + 0.005
    inst = merge_routes([b1, b2], estimator=None, cfg=MergeConfig())
    assert inst.n_clients == 6 and inst.num_vehicles == 3
    assert inst.vehicle_fixed_cost == 3600.0
    # cross-route pairs are estimated, within-route observed
    assert not inst.tt_observed[1, 4] and inst.tt_observed[1, 2]
    assert inst.tt_rel_sd[1, 4] > 0 and inst.tt_rel_sd[1, 2] == 0
    src = inst.meta["tw_source"]
    assert src.count("observed") == 2 and src.count("synthetic") == 4
    synth = [i for i, s in enumerate(src) if s == "synthetic"]
    assert all(inst.tw_late[i] - inst.tw_early[i] <= 7200 + 1e-6 for i in synth)
    assert "haversine speed fit" in inst.meta["estimation_source"]
