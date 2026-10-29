"""Application service layer: orchestrates data, planners, simulator and
disruption engine, and shapes JSON-ready results. Kept free of HTTP concerns
so it can be tested directly."""

from __future__ import annotations

import math
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

import numpy as np

from kairos import __version__
from kairos.config import EVALUATION_SEED_OFFSET, MODELS_DIR
from kairos.data.registry import load_instance
from kairos.data.schema import Instance, instance_to_dict
from kairos.sim.dynamic import DisruptionEvent, run_disruption
from kairos.sim.montecarlo import RouteSpec, simulate, stop_profiles
from kairos.solver.planners import METHODS, Plan, PlannerConfig, plan
from kairos.uncertainty.stochastic import UncertaintyConfig

Progress = Callable[[float, str], None]

LABELS = {
    "plan": "Algorithm-generated plan (PyVRP)",
    "evaluation": "Measured by Monte Carlo simulation on synthetic scenarios (out-of-sample seed stream)",
    "uncertainty": "Synthetic stochastic scenario model (documented assumptions)",
    "estimates": "Model-estimated travel times where stop pairs were not observed",
}


def to_jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): to_jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [to_jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return to_jsonable(x.tolist())
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return f if math.isfinite(f) else None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def uncertainty_from(spec: dict[str, Any] | None) -> UncertaintyConfig:
    spec = dict(spec or {})
    base = UncertaintyConfig.preset(spec.pop("level", "medium"))
    allowed = {"day_sigma", "vehicle_sigma", "arc_sigma", "service_cv", "use_estimation_error"}
    unknown = set(spec) - allowed
    if unknown:
        raise ValueError(f"unknown uncertainty parameters: {sorted(unknown)}")
    for k, v in spec.items():
        if k != "use_estimation_error" and not 0 <= float(v) <= 1.5:
            raise ValueError(f"{k} must lie in [0, 1.5]")
    return UncertaintyConfig(**{**base.to_dict(), **spec})


@lru_cache(maxsize=1)
def travel_time_model():
    path = MODELS_DIR / "traveltime"
    if not (path / "model.json").exists():
        return None
    from kairos.uncertainty.traveltime import TravelTimeModel

    return TravelTimeModel.load(path)


def estimator_for(inst: Instance):
    if inst.source != "amazon":
        return None
    model = travel_time_model()
    if model is None:
        return None
    return model.urgent_estimator(inst.meta.get("station", ""), inst.meta.get("t0_utc_s", 0.0))


# ---------------------------------------------------------------------------
# Plan store (bounded, thread-safe)
# ---------------------------------------------------------------------------


@dataclass
class StoredPlan:
    plan_id: str
    plan: Plan
    payload: dict[str, Any]


class PlanStore:
    def __init__(self, capacity: int = 200):
        self._data: OrderedDict[str, StoredPlan] = OrderedDict()
        self._lock = threading.Lock()
        self.capacity = capacity

    def put(self, p: Plan, payload: dict[str, Any]) -> str:
        pid = uuid.uuid4().hex[:12]
        with self._lock:
            self._data[pid] = StoredPlan(pid, p, payload)
            while len(self._data) > self.capacity:
                self._data.popitem(last=False)
        return pid

    def get(self, pid: str) -> StoredPlan:
        with self._lock:
            if pid not in self._data:
                raise KeyError(f"unknown plan {pid!r}")
            return self._data[pid]


PLANS = PlanStore()


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def health() -> dict[str, Any]:
    from importlib.metadata import version

    return {
        "status": "ok",
        "version": __version__,
        "solver": f"PyVRP {version('pyvrp')}",
        "lightgbm": version("lightgbm"),
        "travel_time_model": travel_time_model() is not None,
    }


def get_instance(instance_id: str) -> dict[str, Any]:
    inst = load_instance(instance_id)
    d = instance_to_dict(inst)
    d["labels"] = LABELS
    if inst.source == "amazon":
        owner = inst.meta.get("route_owner", [])
        src = inst.meta.get("tw_source", [])
        for s in d["stops"]:
            i = s["index"]
            s["historical_route"] = owner[i] if i < len(owner) else None
            s["tw_source"] = src[i] if i < len(src) else None
    return to_jsonable(d)


def _evaluate(inst: Instance, routes: list[RouteSpec], cfg: UncertaintyConfig, n: int, seed: int):
    return simulate(inst, routes, cfg, n, seed + EVALUATION_SEED_OFFSET)


def _plan_payload(inst: Instance, p: Plan, sim, eval_scenarios: int, seed: int) -> dict[str, Any]:
    d = p.to_dict()
    d["evaluation"] = sim.metrics
    d["evaluation_meta"] = {
        "n_scenarios": eval_scenarios,
        "seed_stream": seed + EVALUATION_SEED_OFFSET,
        "label": LABELS["evaluation"],
    }
    d["stop_profiles"] = stop_profiles(inst, sim)
    d["labels"] = LABELS
    return d


def run_plan(
    instance_id: str,
    method: str = "reliability",
    target: float = 0.95,
    uncertainty: dict[str, Any] | None = None,
    iterations: int = 5000,
    seed: int = 0,
    eval_scenarios: int = 200,
    planning_scenarios: int = 100,
    progress: Progress | None = None,
) -> dict[str, Any]:
    inst = load_instance(instance_id)
    cfg = uncertainty_from(uncertainty)
    pc = PlannerConfig(
        method=method,
        target=target,
        iterations=iterations,
        seed=seed,
        planning_scenarios=planning_scenarios,
        uncertainty=cfg,
    )
    p = plan(inst, pc, progress=lambda f, m: progress and progress(0.85 * f, m))
    if progress:
        progress(0.9, f"Evaluating on {eval_scenarios} out-of-sample scenarios")
    sim = _evaluate(inst, p.routes, cfg, eval_scenarios, seed)
    payload = _plan_payload(inst, p, sim, eval_scenarios, seed)
    payload["plan_id"] = PLANS.put(p, payload)
    return to_jsonable(payload)


def _paired(base, other) -> dict[str, Any]:
    """Paired differences (other - base) over common scenarios."""

    def per_scen(sim):
        tw = sim.tw_nodes
        late = sim.lateness[:, tw] > 1e-6
        return 1.0 - late.sum(1) / max(len(tw), 1), sim.lateness[:, tw].sum(1), sim.overtime.sum(1)

    out = {}
    for name, a, b in zip(("on_time_rate", "lateness_total", "overtime"), per_scen(base), per_scen(other)):
        d = b - a
        se = d.std(ddof=1) / np.sqrt(len(d)) if len(d) > 1 else 0.0
        out[name] = {"mean": float(d.mean()), "ci95": [float(d.mean() - 1.96 * se), float(d.mean() + 1.96 * se)]}
    out["distance"] = {"mean": float(other.distance - base.distance), "relative": float(other.distance / base.distance - 1)}
    return out


def run_compare(
    instance_id: str,
    methods: list[str] | None = None,
    target: float = 0.95,
    uncertainty: dict[str, Any] | None = None,
    iterations: int = 5000,
    seed: int = 0,
    eval_scenarios: int = 200,
    planning_scenarios: int = 100,
    progress: Progress | None = None,
) -> dict[str, Any]:
    methods = methods or ["deterministic", "reliability"]
    bad = [m for m in methods if m not in METHODS]
    if bad:
        raise ValueError(f"unknown methods {bad}")
    if "deterministic" not in methods:
        methods = ["deterministic", *methods]
    inst = load_instance(instance_id)
    cfg = uncertainty_from(uncertainty)
    results: dict[str, Any] = {}
    sims = {}
    for i, m in enumerate(methods):
        span = 1.0 / len(methods)

        def sub(f, msg, i=i, m=m):
            if progress:
                progress(min(0.99, (i + f) * span), f"{m}: {msg}")

        pc = PlannerConfig(method=m, target=target, iterations=iterations, seed=seed,
                           planning_scenarios=planning_scenarios, uncertainty=cfg)
        p = plan(inst, pc, progress=lambda f, msg: sub(0.9 * f, msg))
        sub(0.92, "evaluating")
        sim = _evaluate(inst, p.routes, cfg, eval_scenarios, seed)
        sims[m] = sim
        payload = _plan_payload(inst, p, sim, eval_scenarios, seed)
        payload["plan_id"] = PLANS.put(p, payload)
        results[m] = payload
    paired = {m: _paired(sims["deterministic"], sims[m]) for m in methods if m != "deterministic"}
    return to_jsonable(
        {
            "instance_id": instance_id,
            "target": target,
            "uncertainty": cfg.to_dict(),
            "iterations": iterations,
            "seed": seed,
            "eval_scenarios": eval_scenarios,
            "plans": results,
            "paired_vs_deterministic": paired,
            "labels": LABELS,
        }
    )


def run_disruption_job(
    plan_id: str,
    event: dict[str, Any],
    policies: list[str] | None = None,
    target: float | None = None,
    iterations: int = 2000,
    seed: int = 0,
    eval_scenarios: int = 200,
    progress: Progress | None = None,
) -> dict[str, Any]:
    stored = PLANS.get(plan_id)
    p = stored.plan
    inst = load_instance(p.instance_id)
    ev = DisruptionEvent(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in event.items()})
    if progress:
        progress(0.1, "Observing fleet state and applying event")
    out = run_disruption(
        inst,
        p.routes,
        ev,
        p.config.uncertainty,
        policies=tuple(policies or ("hold", "reoptimise", "reliability")),
        target=target if target is not None else p.config.target,
        iterations=iterations,
        seed=seed,
        eval_scenarios=eval_scenarios,
        estimator=estimator_for(inst),
    )
    new_inst: Instance = out.pop("instance")
    if out["new_node"] is not None:
        k = out["new_node"]
        out["new_stop"] = {
            "index": k,
            "x": float(new_inst.coords[k, 0]),
            "y": float(new_inst.coords[k, 1]),
            "tw_early": float(new_inst.tw_early[k]),
            "tw_late": float(new_inst.tw_late[k]),
            "service": float(new_inst.service[k]),
            "estimated_travel": bool(new_inst.tt_rel_sd[k].any()),
        }
    out["plan_id"] = plan_id
    out["labels"] = {**LABELS, "event": "Synthetic disruption (user-configured)"}
    out["metrics_scope"] = "Residual horizon after the event (stops not yet completed)"
    if progress:
        progress(1.0, "Replanning complete")
    return to_jsonable(out)
