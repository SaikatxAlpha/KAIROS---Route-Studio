"""Run KAIROS experiment suites and store results under artifacts/experiments/.

Suites
  static_solomon     56 Solomon instances x 4 planners (baseline, buffer, selection, KAIROS)
  static_amazon      merged Amazon station-day instances x 4 planners
  target_sweep       reliability target 0.85..0.98 on a Solomon subset
  uncertainty_levels low / medium / high variability on a Solomon subset
  misspecification   planner assumes dispersion x{0.5,0.75,1,1.5} of the true model
  dynamic_solomon    5 disruption types x {det, KAIROS} base plans x 3 replanning policies
  dynamic_amazon     same on Amazon instances

Usage
  python scripts/run_experiments.py --suite static_solomon [--quick] [--workers 8]
  python scripts/run_experiments.py --suite all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kairos.config import EXPERIMENTS_DIR  # noqa: E402
from kairos.data.registry import list_instances  # noqa: E402
from kairos.eval.experiments import (  # noqa: E402
    dynamic_run,
    environment,
    run_parallel,
    stamp,
    static_run,
    summarise_dynamic,
    summarise_static,
)
from kairos.uncertainty.stochastic import UncertaintyConfig  # noqa: E402

METHODS = ["deterministic", "buffered", "saa_select", "reliability"]
SUBSET = ["R101", "R105", "R109", "R202", "C101", "C105", "C202", "C206", "RC101", "RC105", "RC202", "RC206"]
EVENTS = ["traffic", "breakdown", "urgent_order", "service_shock", "weather"]


def solomon_ids(quick: bool, subset: bool = False) -> list[str]:
    if subset:
        names = SUBSET[:4] if quick else SUBSET
        return [f"solomon/{n}" for n in names]
    ids = [r["id"] for r in list_instances("solomon")]
    return ids[::7] if quick else ids


def amazon_ids(quick: bool) -> list[str]:
    ids = [r["id"] for r in list_instances("amazon")]
    return ids[:3] if quick else ids


def save(name: str, payload: dict) -> Path:
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPERIMENTS_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=1, default=float))
    print(f"saved {path}")
    return path


def strip_vectors(rows):
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]


def static_suite(name, ids, args, *, targets=(0.95,), levels=("medium",), scales=(1.0,), methods=METHODS, title=""):
    jobs = []
    for iid in ids:
        for level in levels:
            true_cfg = UncertaintyConfig.preset(level)
            for scale in scales:
                for target in targets:
                    for m in methods:
                        if m == "deterministic" and (scale != 1.0 or target != targets[0]):
                            # baseline is unaffected by target / planner dispersion; run once
                            continue
                        jobs.append({
                            "instance_id": iid, "method": m, "target": target, "level": level,
                            "planner_scale": scale, "iterations": args.iterations, "seed": args.seed,
                            "eval_scenarios": args.eval_scenarios, "planning_scenarios": 100,
                            "planner_uncertainty": true_cfg.scaled(scale).to_dict(),
                            "eval_uncertainty": true_cfg.to_dict(),
                        })
    print(f"{name}: {len(jobs)} runs on {len(ids)} instances")
    rows = run_parallel(static_run, jobs, args.workers)
    summaries = {}
    for level in levels:
        for scale in scales:
            for target in targets:
                sel = [r for r in rows if r.get("level") == level
                       and ((r.get("method") == "deterministic") or (r.get("planner_scale") == scale and r.get("target") == target))]
                summaries[f"{level}|x{scale}|{target}"] = summarise_static(sel, target=target)
    failures = [r for r in rows if r.get("status") != "ok"]
    payload = {
        "title": title or name,
        "created": stamp(),
        "config": {"iterations": args.iterations, "seed": args.seed, "eval_scenarios": args.eval_scenarios,
                   "planning_scenarios": 100, "targets": list(targets), "levels": list(levels),
                   "planner_scales": list(scales), "methods": methods, "instances": ids,
                   "workers": args.workers, "quick": args.quick},
        "environment": environment(),
        "summaries": summaries,
        "n_runs": len(rows),
        "n_failed": len(failures),
        "rows": strip_vectors(rows),
    }
    payload["summary"] = headline_static(summaries, targets[0], levels[0])
    payload["summary_by_target"] = {str(t): headline_static(summaries, t, levels[0]) for t in targets}
    save(name, payload)
    return payload


def headline_static(summaries, target, level):
    s = summaries.get(f"{level}|x1.0|{target}")
    if not s:
        return None
    out = {}
    for e in s["overall"]:
        d = {"on_time_rate": e["mean"]["on_time_rate"], "distance": e["mean"]["distance"],
             "target_attainment_rate": e.get("target_attainment_rate"), "n": e["n_instances"]}
        if "paired_vs_baseline" in e:
            p = e["paired_vs_baseline"]
            d.update({"delta_on_time_pt": p["on_time_rate_pt"]["mean"], "delta_on_time_ci": p["on_time_rate_pt"]["ci95"],
                      "delta_distance_pct": p["distance_rel_pct"]["mean"], "delta_distance_ci": p["distance_rel_pct"]["ci95"],
                      "wilcoxon_p_on_time": p["on_time_rate_pt"]["wilcoxon_p"]})
        out[e["method"]] = d
    return out


def dynamic_suite(name, ids, args, title=""):
    cfg = UncertaintyConfig.preset("medium").to_dict()
    jobs = []
    for iid in ids:
        for bm in ("deterministic", "reliability"):
            jobs.append({"instance_id": iid, "base_method": bm, "target": 0.95, "iterations": args.iterations,
                         "replan_iterations": args.replan_iterations, "seed": args.seed, "events": EVENTS,
                         "repeats": args.repeats, "eval_scenarios": args.eval_scenarios // 2 if args.eval_scenarios > 200 else args.eval_scenarios,
                         "uncertainty": cfg})
    print(f"{name}: {len(jobs)} plan jobs x {len(EVENTS)} events x {args.repeats} repeats")
    nested = run_parallel(dynamic_run, jobs, args.workers)
    rows = [r for group in nested for r in (group if isinstance(group, list) else [group])]
    summary = summarise_dynamic(rows)
    failures = [r for r in rows if r.get("status") != "ok"]
    head = {}
    for c in summary["cells"]:
        if c["event"] == "all":
            head[f"{c['base_method']}+{c['policy']}"] = {
                "on_time_rate": c["mean"]["on_time_rate"],
                "delta_on_time_pt": c.get("paired_vs_det_hold", {}).get("on_time_rate_pt", {}).get("mean"),
                "delta_on_time_ci": c.get("paired_vs_det_hold", {}).get("on_time_rate_pt", {}).get("ci95"),
                "delta_distance_pct": c.get("paired_vs_det_hold", {}).get("distance_rel_pct", {}).get("mean"),
                "replan_runtime_s": c["mean"]["runtime_s"], "n": c["n"],
            }
    payload = {
        "title": title or name,
        "created": stamp(),
        "config": {"iterations": args.iterations, "replan_iterations": args.replan_iterations, "seed": args.seed,
                   "events": EVENTS, "repeats": args.repeats, "target": 0.95, "uncertainty": cfg, "instances": ids,
                   "base_methods": ["deterministic", "reliability"], "policies": ["hold", "reoptimise", "reliability"]},
        "environment": environment(),
        "summary": head,
        "cells": summary["cells"],
        "n_runs": len(rows),
        "n_failed": len(failures),
        "rows": rows,
    }
    save(name, payload)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="all")
    ap.add_argument("--quick", action="store_true", help="small smoke-scale run")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--iterations", type=int, default=5000)
    ap.add_argument("--replan-iterations", type=int, default=2000)
    ap.add_argument("--eval-scenarios", type=int, default=500)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    if args.quick:
        args.iterations, args.eval_scenarios, args.repeats, args.replan_iterations = 600, 100, 1, 400

    suites = args.suite.split(",") if args.suite != "all" else [
        "static_solomon", "target_sweep", "uncertainty_levels", "misspecification", "dynamic_solomon",
        "static_amazon", "dynamic_amazon",
    ]
    for s in suites:
        if s == "static_solomon":
            static_suite(s, solomon_ids(args.quick), args, title="Static planning — Solomon VRPTW (56 instances)")
        elif s == "static_amazon":
            ids = amazon_ids(args.quick)
            if not ids:
                print("no Amazon instances available; run scripts/build_amazon_instances.py")
                continue
            static_suite(s, ids, args, targets=(0.95, 0.99), title="Static planning — Amazon merged station-days")
        elif s == "target_sweep":
            static_suite(s, solomon_ids(args.quick, subset=True), args, targets=(0.85, 0.9, 0.95, 0.98),
                         methods=["deterministic", "reliability"], title="Reliability target sweep (Solomon subset)")
        elif s == "uncertainty_levels":
            static_suite(s, solomon_ids(args.quick, subset=True), args, levels=("low", "medium", "high"),
                         methods=["deterministic", "buffered", "reliability"], title="Uncertainty level sensitivity (Solomon subset)")
        elif s == "misspecification":
            static_suite(s, solomon_ids(args.quick, subset=True), args, scales=(0.5, 0.75, 1.0, 1.5),
                         methods=["deterministic", "reliability"], title="Planner misspecification (Solomon subset)")
        elif s == "dynamic_solomon":
            dynamic_suite(s, solomon_ids(args.quick, subset=True), args, title="Dynamic disruptions — Solomon subset")
        elif s == "dynamic_amazon":
            ids = amazon_ids(args.quick)
            if not ids:
                print("no Amazon instances available")
                continue
            dynamic_suite(s, ids[: max(3, len(ids) // 2)], args, title="Dynamic disruptions — Amazon")
        else:
            sys.exit(f"unknown suite {s}")


if __name__ == "__main__":
    main()
