"""Reproducible experiment suites.

Every run is defined by (instance, method/policy, seeds, uncertainty config)
and executed with iteration-based solver stopping, so results are
reproducible for a given seed. Planner (in-sample) and evaluation scenario
streams are disjoint. Methods are compared on identical evaluation scenarios
(common random numbers) and summarised with paired statistics across
instances. Failed runs are recorded, never dropped silently.
"""

from __future__ import annotations

import os
import platform
import time
import traceback
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from importlib.metadata import version
from typing import Any, Callable

import numpy as np

from kairos.config import EVALUATION_SEED_OFFSET
from kairos.data.registry import load_instance
from kairos.data.schema import Instance
from kairos.eval.stats import paired_summary
from kairos.sim.dynamic import EVENT_TYPES, DisruptionEvent, run_disruption
from kairos.sim.montecarlo import simulate
from kairos.solver.planners import PlannerConfig, plan
from kairos.uncertainty.stochastic import UncertaintyConfig

METRIC_KEYS = (
    "on_time_rate",
    "p_all_on_time",
    "violations_mean",
    "lateness_total_mean",
    "overtime_mean",
    "p_overtime",
    "distance",
    "n_routes",
    "duration_total_mean",
)


def environment() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "pyvrp": version("pyvrp"),
        "numpy": version("numpy"),
        "lightgbm": version("lightgbm"),
        "cpu_count": os.cpu_count(),
    }


def group_of(inst: Instance) -> str:
    if inst.source == "solomon":
        return inst.meta["group"]
    if inst.source == "amazon":
        return "Amazon"
    return "Synthetic"


# ---------------------------------------------------------------------------
# Static planning runs
# ---------------------------------------------------------------------------


def static_run(args: dict[str, Any]) -> dict[str, Any]:
    """One (instance, method, target, planner-uncertainty, eval-uncertainty) run."""
    warnings.filterwarnings("ignore")
    inst = load_instance(args["instance_id"])
    planner_cfg = UncertaintyConfig(**args["planner_uncertainty"])
    eval_cfg = UncertaintyConfig(**args["eval_uncertainty"])
    pc = PlannerConfig(
        method=args["method"],
        target=args["target"],
        iterations=args["iterations"],
        seed=args["seed"],
        planning_scenarios=args.get("planning_scenarios", 100),
        uncertainty=planner_cfg,
        time_limit=args.get("time_limit", 60.0),
    )
    row: dict[str, Any] = {k: v for k, v in args.items() if k not in ("planner_uncertainty", "eval_uncertainty")}
    row["group"] = group_of(inst)
    row["n_clients"] = inst.n_clients
    try:
        p = plan(inst, pc)
        sim = simulate(inst, p.routes, eval_cfg, args["eval_scenarios"], args["seed"] + EVALUATION_SEED_OFFSET)
        row.update({k: sim.metrics[k] for k in METRIC_KEYS})
        row.update(
            {
                "status": "ok",
                "beta": p.beta,
                "planned_feasible": p.solve.feasible,
                "unplanned": len(p.solve.unplanned),
                "target_attained_in_sample": p.target_attained,
                "runtime_s": p.runtime_total,
                "solver_iterations": p.solve.iterations,
                "n_candidates": len(p.candidates),
                # per-scenario vectors for paired CRN analysis
                "_on_time_vec": (1 - (sim.lateness[:, sim.tw_nodes] > 1e-6).mean(1)).round(5).tolist(),
            }
        )
    except Exception as exc:  # noqa: BLE001 - recorded as a failed run
        row.update({"status": "error", "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-800:]})
    return row


def summarise_static(rows: list[dict[str, Any]], baseline: str = "deterministic", target: float | None = None) -> dict[str, Any]:
    ok = [r for r in rows if r["status"] == "ok"]
    methods = sorted({r["method"] for r in ok}, key=lambda m: ["deterministic", "buffered", "saa_select", "reliability"].index(m))
    groups = sorted({r["group"] for r in ok})
    idx = {(r["instance_id"], r["method"]): r for r in ok}
    out: dict[str, Any] = {"by_group": [], "overall": [], "failures": [r for r in rows if r["status"] != "ok"]}
    for scope, gs in [("overall", None), *[(g, g) for g in groups]]:
        insts = sorted({r["instance_id"] for r in ok if gs is None or r["group"] == gs})
        for m in methods:
            pairs = [(idx[(i, m)], idx[(i, baseline)]) for i in insts if (i, m) in idx and (i, baseline) in idx]
            if not pairs:
                continue
            a = np.array([[p[0][k] for k in METRIC_KEYS] for p in pairs], dtype=float)
            b = np.array([[p[1][k] for k in METRIC_KEYS] for p in pairs], dtype=float)
            col = {k: j for j, k in enumerate(METRIC_KEYS)}
            entry = {
                "scope": scope,
                "method": m,
                "n_instances": len(pairs),
                "mean": {k: float(a[:, col[k]].mean()) for k in METRIC_KEYS},
                "runtime_s_mean": float(np.mean([p[0]["runtime_s"] for p in pairs])),
            }
            if target is not None:
                entry["target_attainment_rate"] = float(np.mean(a[:, col["on_time_rate"]] >= target))
            if m != baseline:
                entry["paired_vs_baseline"] = {
                    "on_time_rate_pt": paired_summary((a[:, col["on_time_rate"]] - b[:, col["on_time_rate"]]) * 100),
                    "lateness_total_rel": paired_summary(
                        (a[:, col["lateness_total_mean"]] - b[:, col["lateness_total_mean"]])
                        / np.maximum(b[:, col["lateness_total_mean"]], 1e-9)
                        * 100
                    ),
                    "distance_rel_pct": paired_summary((a[:, col["distance"]] / b[:, col["distance"]] - 1) * 100),
                    "vehicles_delta": paired_summary(a[:, col["n_routes"]] - b[:, col["n_routes"]]),
                    "p_all_on_time_pt": paired_summary((a[:, col["p_all_on_time"]] - b[:, col["p_all_on_time"]]) * 100),
                }
            (out["overall"] if scope == "overall" else out["by_group"]).append(entry)
    return out


# ---------------------------------------------------------------------------
# Dynamic (disruption) runs
# ---------------------------------------------------------------------------


def make_event(inst: Instance, kind: str, routes, rng: np.random.Generator) -> DisruptionEvent:
    """Seeded synthetic event generator used by the dynamic experiments."""
    h0, h1 = inst.tw_early[0], inst.tw_late[0]
    used = [r for r in routes if r.stops]
    # Event time: 25-45% into the span actually used by the plan.
    end = max(h0 + 1, min(h1, max(inst.tw_late[r.stops[-1]] for r in used)))
    tau = float(h0 + rng.uniform(0.25, 0.45) * (end - h0))
    xy = inst.coords[1:]
    span = float(np.ptp(xy[:, 0]) + np.ptp(xy[:, 1])) / 2
    geo = inst.coord_system == "wgs84"
    radius_unit = span * (111.0 if geo else 1.0)
    c = tuple(xy[rng.integers(len(xy))])
    if kind == "traffic":
        return DisruptionEvent("traffic", tau, factor=1.6, center=c, radius=0.3 * radius_unit)
    if kind == "service_shock":
        return DisruptionEvent("service_shock", tau, factor=2.0, center=c, radius=0.3 * radius_unit)
    if kind == "weather":
        return DisruptionEvent("weather", tau, factor=1.3)
    if kind == "breakdown":
        return DisruptionEvent("breakdown", tau, vehicle=int(rng.integers(len(used))))
    if kind == "urgent_order":
        jitter = rng.normal(0, 0.03 * span, size=2)
        loc = (float(c[0] + jitter[0]), float(c[1] + jitter[1]))
        return DisruptionEvent(
            "urgent_order", tau, location=loc, window=0.15 * (h1 - h0),
            service=float(np.median(inst.service[1:])), demand=float(min(np.median(inst.demand[1:]), inst.capacity)),
        )
    raise ValueError(kind)


def dynamic_run(args: dict[str, Any]) -> list[dict[str, Any]]:
    warnings.filterwarnings("ignore")
    inst = load_instance(args["instance_id"])
    cfg = UncertaintyConfig(**args["uncertainty"])
    rows = []
    estimator = None
    if inst.source == "amazon":
        from kairos.service import estimator_for

        estimator = estimator_for(inst)
    try:
        pc = PlannerConfig(method=args["base_method"], target=args["target"], iterations=args["iterations"],
                           seed=args["seed"], uncertainty=cfg, time_limit=60.0)
        p = plan(inst, pc)
    except Exception as exc:  # noqa: BLE001
        return [{**args, "status": "error", "stage": "plan", "error": f"{type(exc).__name__}: {exc}"}]
    for kind in args["events"]:
        for rep in range(args["repeats"]):
            rng = np.random.default_rng([args["seed"], rep, EVENT_TYPES.index(kind), 17])
            base = {k: v for k, v in args.items() if k not in ("uncertainty", "events")}
            base.update({"event": kind, "repeat": rep, "group": group_of(inst)})
            try:
                ev = make_event(inst, kind, p.routes, rng)
                out = run_disruption(
                    inst, p.routes, ev, cfg, target=args["target"], iterations=args["replan_iterations"],
                    seed=args["seed"] + 101 * rep, eval_scenarios=args["eval_scenarios"],
                    planning_scenarios=args.get("planning_scenarios", 60), estimator=estimator, time_limit=60.0,
                )
                for pol, res in out["policies"].items():
                    m = res["metrics"]
                    rows.append({
                        **base, "status": "ok", "policy": pol, "event_time": ev.time,
                        "n_completed": out["state"]["n_completed"],
                        **{k: m[k] for k in METRIC_KEYS}, "unserved": m["unserved"],
                        "n_moved": res["diff"]["n_moved"], "runtime_s": res["runtime_s"], "beta": res["beta"],
                    })
            except Exception as exc:  # noqa: BLE001
                rows.append({**base, "status": "error", "error": f"{type(exc).__name__}: {exc}",
                             "trace": traceback.format_exc()[-800:]})
    return rows


def summarise_dynamic(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in rows if r["status"] == "ok"]
    key = lambda r: (r["instance_id"], r["base_method"], r["event"], r["repeat"])  # noqa: E731
    idx = {(key(r), r["policy"]): r for r in ok}
    out: dict[str, Any] = {"cells": [], "failures": [r for r in rows if r["status"] != "ok"]}
    combos = sorted({(r["group"] == "Amazon", r["base_method"], r["policy"]) for r in ok})
    events = sorted({r["event"] for r in ok}) + ["all"]
    for amazon, bm, pol in combos:
        for ev in events:
            sel = [r for r in ok if (r["group"] == "Amazon") == amazon and r["base_method"] == bm and r["policy"] == pol
                   and (ev == "all" or r["event"] == ev)]
            if not sel:
                continue
            # paired against (deterministic base plan, hold) for the same disruption
            ref = [idx.get(((r["instance_id"], "deterministic", r["event"], r["repeat"]), "hold")) for r in sel]
            pairs = [(r, q) for r, q in zip(sel, ref) if q is not None]
            cell = {
                "benchmark": "Amazon" if amazon else "Solomon",
                "base_method": bm,
                "policy": pol,
                "event": ev,
                "n": len(sel),
                "mean": {k: float(np.mean([r[k] for r in sel])) for k in ("on_time_rate", "lateness_total_mean", "distance", "n_routes", "runtime_s", "n_moved", "unserved", "p_overtime")},
            }
            if pairs and not (bm == "deterministic" and pol == "hold"):
                cell["paired_vs_det_hold"] = {
                    "on_time_rate_pt": paired_summary(np.array([(a["on_time_rate"] - b["on_time_rate"]) * 100 for a, b in pairs])),
                    "lateness_total_rel": paired_summary(np.array([
                        (a["lateness_total_mean"] - b["lateness_total_mean"]) / max(b["lateness_total_mean"], 1e-9) * 100 for a, b in pairs])),
                    "distance_rel_pct": paired_summary(np.array([(a["distance"] / b["distance"] - 1) * 100 for a, b in pairs])),
                }
            out["cells"].append(cell)
    return out


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------


def run_parallel(fn: Callable, jobs: list[dict[str, Any]], workers: int, log=print) -> list[Any]:
    results: list[Any] = []
    t0 = time.time()
    if workers <= 1:
        for i, j in enumerate(jobs):
            results.append(fn(j))
            log(f"  [{i + 1}/{len(jobs)}] {time.time() - t0:.0f}s")
        return results
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, j): j for j in jobs}
        for i, f in enumerate(as_completed(futs)):
            try:
                results.append(f.result())
            except Exception as exc:  # noqa: BLE001 - worker crash recorded
                j = futs[f]
                results.append({**{k: v for k, v in j.items() if not isinstance(v, dict)}, "status": "error",
                                "error": f"worker crashed: {exc}"})
            if (i + 1) % max(1, len(jobs) // 20) == 0 or i + 1 == len(jobs):
                log(f"  [{i + 1}/{len(jobs)}] {time.time() - t0:.0f}s")
    return results


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
