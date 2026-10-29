import time

import pytest
from fastapi.testclient import TestClient

from kairos.api.app import app

client = TestClient(app)


def _wait(job, timeout=120):
    t0 = time.time()
    while True:
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["status"] in ("done", "error"):
            return j
        assert time.time() - t0 < timeout, "job timed out"
        time.sleep(0.2)


def test_health_and_catalogue():
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["solver"].startswith("PyVRP")
    ds = {d["source"]: d for d in client.get("/api/datasets").json()}
    assert ds["solomon"]["n_instances"] == 56
    sol = client.get("/api/instances?source=solomon").json()
    assert len(sol) == 56
    inst = client.get("/api/instances/solomon/R101").json()
    assert len(inst["stops"]) == 101 and inst["stops"][0]["is_depot"]
    assert "observed" in inst["provenance"]


def test_errors():
    assert client.get("/api/instances/solomon/NOPE").status_code == 404
    assert client.get("/api/instances?source=bogus").status_code == 422
    assert client.post("/api/plans", json={"instance_id": "solomon/R101", "target": 1.4}).status_code == 422
    assert client.post("/api/plans", json={"instance_id": "missing/x"}).status_code == 404
    assert client.post("/api/compare", json={"instance_id": "solomon/R101", "methods": ["magic"]}).status_code == 422
    assert client.get("/api/jobs/doesnotexist").status_code == 404
    assert client.get("/api/plans/doesnotexist").status_code == 404
    bad_event = {"plan_id": "x", "event": {"type": "breakdown", "time": 10}}
    assert client.post("/api/disruptions", json=bad_event).status_code == 404
    assert client.post("/api/disruptions", json={"plan_id": "x", "event": {"type": "tsunami", "time": 1}}).status_code == 422
    assert client.get("/api/experiments/nope").status_code == 404


@pytest.fixture(scope="module")
def compared():
    body = {"instance_id": "synthetic/demo-40-s7", "methods": ["deterministic", "reliability"],
            "iterations": 600, "eval_scenarios": 60, "planning_scenarios": 20, "target": 0.9}
    r = client.post("/api/compare", json=body)
    assert r.status_code == 202
    j = _wait(r.json())
    assert j["status"] == "done", j.get("error")
    return j["result"]


def test_compare_flow(compared):
    plans = compared["plans"]
    assert set(plans) == {"deterministic", "reliability"}
    for p in plans.values():
        assert p["evaluation"]["n_scenarios"] == 60
        assert len(p["stop_profiles"]) == 40
        assert sum(len(r["stops"]) for r in p["routes"]) == 40
    assert "on_time_rate" in compared["paired_vs_deterministic"]["reliability"]
    pid = plans["reliability"]["plan_id"]
    assert client.get(f"/api/plans/{pid}").json()["method"] == "reliability"


def test_disruption_flow(compared):
    pid = compared["plans"]["deterministic"]["plan_id"]
    body = {"plan_id": pid, "event": {"type": "breakdown", "time": 120, "vehicle": 0},
            "iterations": 300, "eval_scenarios": 40}
    j = _wait(client.post("/api/disruptions", json=body).json())
    assert j["status"] == "done", j.get("error")
    res = j["result"]
    assert set(res["policies"]) == {"hold", "reoptimise", "reliability"}
    assert any(v["status"] == "broken" for v in res["state"]["vehicles"])
    # invalid vehicle index is reported as a job error, not a crash
    body["event"]["vehicle"] = 99
    j = _wait(client.post("/api/disruptions", json=body).json())
    assert j["status"] == "error" and "vehicle index" in j["error"]


def test_experiments_listing():
    r = client.get("/api/experiments")
    assert r.status_code == 200 and isinstance(r.json(), list)
