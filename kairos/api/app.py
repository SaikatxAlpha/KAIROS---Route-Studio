"""KAIROS HTTP API (FastAPI).

Expensive operations (planning, comparison, disruption replanning) run as
background jobs: the POST returns a job id and the client polls
``GET /api/jobs/{id}`` for progress and the result.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from kairos import service
from kairos.api.jobs import JobManager
from kairos.config import AMAZON_PROCESSED_DIR, EXPERIMENTS_DIR, MAX_SCENARIOS, REPO_ROOT
from kairos.data import registry

app = FastAPI(title="KAIROS API", version=service.__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
jobs = JobManager(workers=2)

Method = Literal["deterministic", "buffered", "saa_select", "reliability"]
Policy = Literal["hold", "reoptimise", "reliability"]


class UncertaintySpec(BaseModel):
    level: Literal["low", "medium", "high"] = "medium"
    day_sigma: float | None = Field(None, ge=0, le=1.5)
    vehicle_sigma: float | None = Field(None, ge=0, le=1.5)
    arc_sigma: float | None = Field(None, ge=0, le=1.5)
    service_cv: float | None = Field(None, ge=0, le=1.5)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class PlanRequest(BaseModel):
    instance_id: str
    method: Method = "reliability"
    target: float = Field(0.95, ge=0.5, le=0.999)
    uncertainty: UncertaintySpec = UncertaintySpec()
    iterations: int = Field(5000, ge=50, le=50_000)
    seed: int = Field(0, ge=0, le=2**31 - 1)
    eval_scenarios: int = Field(200, ge=20, le=MAX_SCENARIOS)
    planning_scenarios: int = Field(100, ge=10, le=1000)


class CompareRequest(BaseModel):
    instance_id: str
    methods: list[Method] = ["deterministic", "reliability"]
    target: float = Field(0.95, ge=0.5, le=0.999)
    uncertainty: UncertaintySpec = UncertaintySpec()
    iterations: int = Field(5000, ge=50, le=50_000)
    seed: int = Field(0, ge=0, le=2**31 - 1)
    eval_scenarios: int = Field(200, ge=20, le=MAX_SCENARIOS)
    planning_scenarios: int = Field(100, ge=10, le=1000)


class EventSpec(BaseModel):
    type: Literal["traffic", "breakdown", "urgent_order", "service_shock", "weather"]
    time: float = Field(..., ge=0)
    factor: float = Field(1.5, ge=0.2, le=5)
    center: tuple[float, float] | None = None
    radius: float | None = Field(None, gt=0)
    vehicle: int | None = Field(None, ge=0)
    duration: float | None = Field(None, gt=0)
    location: tuple[float, float] | None = None
    window: float | None = Field(None, gt=0)
    service: float | None = Field(None, ge=0)
    demand: float = Field(0.0, ge=0)


class DisruptionRequest(BaseModel):
    plan_id: str
    event: EventSpec
    policies: list[Policy] = ["hold", "reoptimise", "reliability"]
    target: float | None = Field(None, ge=0.5, le=0.999)
    iterations: int = Field(2000, ge=50, le=50_000)
    seed: int = Field(0, ge=0, le=2**31 - 1)
    eval_scenarios: int = Field(200, ge=20, le=MAX_SCENARIOS)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc).strip("'\""))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return service.health()


@app.get("/api/datasets")
def datasets() -> list[dict[str, Any]]:
    return service.to_jsonable(registry.datasets())


@app.get("/api/datasets/amazon/profile")
def amazon_profile() -> dict[str, Any]:
    path = AMAZON_PROCESSED_DIR / "profile.json"
    if not path.exists():
        path = REPO_ROOT / "artifacts" / "data_profile" / "amazon_profile.json"
    if not path.exists():
        raise HTTPException(404, "Amazon dataset has not been processed; run scripts/prepare_amazon.py")
    return json.loads(path.read_text())


@app.get("/api/instances")
def instances(source: Literal["amazon", "solomon", "synthetic"] | None = None) -> list[dict[str, Any]]:
    return service.to_jsonable(registry.list_instances(source))


@app.get("/api/instances/{instance_id:path}")
def instance(instance_id: str) -> dict[str, Any]:
    try:
        return service.get_instance(instance_id)
    except (KeyError, FileNotFoundError) as exc:
        raise _not_found(exc) from exc


def _check_instance(instance_id: str) -> None:
    try:
        registry.load_instance(instance_id)
    except (KeyError, FileNotFoundError) as exc:
        raise _not_found(exc) from exc


@app.post("/api/plans", status_code=202)
def create_plan(req: PlanRequest) -> dict[str, Any]:
    _check_instance(req.instance_id)
    kw = req.model_dump()
    kw["uncertainty"] = req.uncertainty.as_dict()
    return jobs.submit("plan", service.run_plan, **kw).view()


@app.post("/api/compare", status_code=202)
def compare(req: CompareRequest) -> dict[str, Any]:
    _check_instance(req.instance_id)
    kw = req.model_dump()
    kw["uncertainty"] = req.uncertainty.as_dict()
    return jobs.submit("compare", service.run_compare, **kw).view()


@app.get("/api/plans/{plan_id}")
def get_plan(plan_id: str) -> dict[str, Any]:
    try:
        return service.PLANS.get(plan_id).payload | {"plan_id": plan_id}
    except KeyError as exc:
        raise _not_found(exc) from exc


@app.post("/api/disruptions", status_code=202)
def disrupt(req: DisruptionRequest) -> dict[str, Any]:
    try:
        service.PLANS.get(req.plan_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    kw = req.model_dump()
    kw["event"] = req.event.model_dump()
    return jobs.submit("disruption", service.run_disruption_job, **kw).view()


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict[str, Any]:
    try:
        return jobs.get(job_id).view()
    except KeyError as exc:
        raise _not_found(exc) from exc


@app.get("/api/experiments")
def experiments() -> list[dict[str, Any]]:
    out = []
    for p in sorted(EXPERIMENTS_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        out.append({"name": p.stem, "title": d.get("title", p.stem), "created": d.get("created"),
                    "summary": d.get("summary")})
    return out


@app.get("/api/experiments/{name}")
def experiment(name: str) -> dict[str, Any]:
    path = EXPERIMENTS_DIR / f"{Path(name).name}.json"
    if not path.exists():
        raise HTTPException(404, f"experiment {name!r} not found")
    return json.loads(path.read_text())


@app.get("/api/models/travel-time")
def travel_time_report() -> dict[str, Any]:
    model = service.travel_time_model()
    if model is None:
        raise HTTPException(404, "travel-time model not trained; run scripts/train_traveltime.py")
    return service.to_jsonable({"report": model.report, "conformal": model.conformal, "params": model.params})


# Serve the built frontend when present (single-process deployment).
_DIST = REPO_ROOT / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "not found")
        target = _DIST / path
        return FileResponse(target if target.is_file() else _DIST / "index.html")
