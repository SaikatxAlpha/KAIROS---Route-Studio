"""Train and validate the travel-time estimation model on Amazon arcs.

Splits are by date (train -> calibration -> test, chronological), produced by
scripts/prepare_amazon.py. Writes:
  artifacts/models/traveltime/              LightGBM quantile models + conformal offsets
  artifacts/experiments/traveltime_model.json   validation report for the UI / README
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kairos.config import AMAZON_PROCESSED_DIR, EXPERIMENTS_DIR, MODELS_DIR  # noqa: E402
from kairos.uncertainty.traveltime import LEVELS, TravelTimeModel, pinball, speed_baseline  # noqa: E402


def load(split: str):
    d = np.load(AMAZON_PROCESSED_DIR / f"arcs_{split}.npz")
    return d["X"], d["y"], d["g"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-train", type=int, default=1_200_000)
    ap.add_argument("--rounds", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    profile = json.loads((AMAZON_PROCESSED_DIR / "profile.json").read_text())
    station_ids = profile["stations"]
    Xtr, ytr, gtr = load("train")
    Xca, yca, gca = load("calibration")
    Xte, yte, gte = load("test")
    rng = np.random.default_rng(args.seed)
    if len(ytr) > args.max_train:
        idx = rng.choice(len(ytr), args.max_train, replace=False)
        Xtr, ytr = Xtr[idx], ytr[idx]
    print(f"train {len(ytr):,} | calibration {len(yca):,} | test {len(yte):,} arcs")

    t0 = time.time()
    model = TravelTimeModel.fit(Xtr, ytr, station_ids, num_rounds=args.rounds, seed=args.seed)
    fit_s = time.time() - t0
    model.calibrate(Xca, yca)
    test = model.evaluate(Xte, yte, groups=gte)
    cal = model.evaluate(Xca, yca, groups=gca)

    # Baseline: per-station log-log speed fit on the same training arcs.
    base_log = speed_baseline(Xtr, ytr, Xte)
    resid = ytr - speed_baseline(Xtr, ytr, Xtr)
    # Baseline interval: empirical residual quantiles from training (no conformal step).
    y = np.exp(yte)
    base_pred = np.exp(base_log)
    baseline = {
        "mae_s": float(np.mean(np.abs(base_pred - y))),
        "mape": float(np.mean(np.abs(base_pred - y) / np.maximum(y, 1.0))),
        "median_ape": float(np.median(np.abs(base_pred - y) / np.maximum(y, 1.0))),
        "pinball_log_0.5": pinball(yte, base_log, 0.5),
        "coverage": [],
    }
    for level in LEVELS:
        a = (1 - level) / 2
        lo, hi = np.quantile(resid, [a, 1 - a])
        inside = (yte >= base_log + lo) & (yte <= base_log + hi)
        baseline["coverage"].append(
            {"nominal": level, "coverage": float(inside.mean()), "rel_width": float(np.exp(hi - lo) - 1)}
        )

    report = {
        "title": "Travel-time estimation model (Amazon, observed average travel times)",
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": {
            "target": "log of observed average stop-to-stop travel time (s), travel_times.json",
            "split": "chronological by date: train / calibration / test",
            "split_dates": profile["split_dates"],
            "n_train_arcs": int(len(ytr)),
            "n_calibration_arcs": int(len(yca)),
            "n_test_arcs": int(len(yte)),
            "arcs_per_route": profile["arcs_per_route"],
        },
        "model": {
            "type": "LightGBM quantile regression, one model per quantile, monotone rearrangement",
            "quantiles": sorted(model.boosters),
            "params": model.params,
            "calibration": "conformalized quantile regression (split conformal) per nominal level",
            "conformal_offsets_log": {str(k): v for k, v in model.conformal.items()},
            "fit_seconds": fit_s,
        },
        "test": test,
        "calibration_set": {"coverage": cal["coverage"]},
        "baseline_speed_fit": baseline,
        "summary": {
            "mae_s": test["mae_s"],
            "baseline_mae_s": baseline["mae_s"],
            "median_ape": test["median_ape"],
            "baseline_median_ape": baseline["median_ape"],
            "coverage_90_conformal": next(r["conformal_coverage"] for r in test["coverage"] if r["nominal"] == 0.9),
            "coverage_90_raw": next(r["raw_coverage"] for r in test["coverage"] if r["nominal"] == 0.9),
        },
        "caveats": [
            "Arcs within one route are dependent; coverage is marginal over arcs and assumes exchangeability "
            "between the calibration and test date blocks.",
            "The interval quantifies uncertainty in the average travel time of an unobserved stop pair, "
            "not day-to-day variability of individual trips (the dataset has no per-trip observations).",
        ],
    }
    model.report = report
    model.save(MODELS_DIR / "traveltime")
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    (EXPERIMENTS_DIR / "traveltime_model.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report["summary"], indent=2))
    for row in test["coverage"]:
        print(row)
    print("baseline", baseline["coverage"])


if __name__ == "__main__":
    main()
