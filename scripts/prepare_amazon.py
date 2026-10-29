"""Ingest, validate, profile and split the Amazon Last Mile dataset.

Outputs (under data/processed/amazon/):
  route_index.csv     one row per route: split, station, date, size, quality flags
  profile.json        dataset profile: counts, missing values, rejected routes
  arcs_<split>.npz    sampled arc features/targets for the travel-time model
  routes/*.json.gz    validated bundles for calibration- and test-date routes

Usage:
  python scripts/prepare_amazon.py [--raw data/raw/amazon] [--arcs-per-route 400] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kairos.config import AMAZON_PROCESSED_DIR, AMAZON_RAW_DIR  # noqa: E402
from kairos.data.amazon import (  # noqa: E402
    AmazonSchemaError,
    build_bundle,
    date_split,
    save_bundle,
)
from kairos.uncertainty.traveltime import arc_features  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=AMAZON_RAW_DIR)
    ap.add_argument("--out", type=Path, default=AMAZON_PROCESSED_DIR)
    ap.add_argument("--arcs-per-route", type=int, default=400)
    ap.add_argument("--limit", type=int, default=0, help="process only the first N routes (debug)")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    import ijson

    raw: Path = args.raw
    out: Path = args.out
    for name in ("route_data.json", "package_data.json", "travel_times.json", "actual_sequences.json"):
        if not (raw / name).exists():
            sys.exit(f"missing {raw / name}; run scripts/download_amazon.sh first")
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print("loading route_data / package_data / actual_sequences ...")
    routes = json.loads((raw / "route_data.json").read_text())
    packages = json.loads((raw / "package_data.json").read_text())  # contains NaN literals
    actual = json.loads((raw / "actual_sequences.json").read_text())
    print(f"  loaded in {time.time() - t0:.1f}s: {len(routes)} routes")

    splits = date_split([r["date_YYYY_MM_DD"] for r in routes.values()])
    stations = sorted({r["station_code"] for r in routes.values()})
    station_ids = {s: i for i, s in enumerate(stations)}
    rng = np.random.default_rng(args.seed)

    arcs: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    index_rows = []
    rejected: Counter = Counter()
    quality_tot: Counter = Counter()
    n_done = 0
    print("streaming travel_times.json ...")
    with open(raw / "travel_times.json", "rb") as f:
        for rid, matrix in ijson.kvitems(f, "", use_float=True):
            if rid not in routes:
                rejected["not_in_route_data"] += 1
                continue
            r = routes[rid]
            split = splits[r["date_YYYY_MM_DD"]]
            try:
                b = build_bundle(rid, r, packages.get(rid, {}), matrix, actual.get(rid))
            except AmazonSchemaError as exc:
                rejected[str(exc).split(": ", 1)[-1][:60]] += 1
                continue
            for k, v in b.quality.items():
                quality_tot[k] += v
            n = len(b.stop_ids)
            # --- arc sample for the travel-time model
            m = min(args.arcs_per_route, n * (n - 1))
            ii = rng.integers(0, n, size=m * 2)
            jj = rng.integers(0, n, size=m * 2)
            keep = ii != jj
            ii, jj = ii[keep][:m], jj[keep][:m]
            y = b.travel_time[ii, jj]
            ok = (y > 0) & (y < 4 * 3600)
            ii, jj, y = ii[ok], jj[ok], y[ok]
            X = arc_features(
                b.lat[ii], b.lng[ii], b.lat[jj], b.lng[jj],
                [b.zones[i] for i in ii], [b.zones[j] for j in jj],
                ii == 0, jj == 0, float(b.lat[0]), float(b.lng[0]),
                station_ids[b.station], b.departure_s / 3600.0,
            )
            arcs[split]["X"].append(X)
            arcs[split]["y"].append(np.log(y).astype(np.float32))
            arcs[split]["g"].append(np.full(len(y), n_done, dtype=np.int32))
            # --- persist bundles needed for calibration/test experiments
            if split in ("calibration", "test"):
                save_bundle(b, out / "routes")
            index_rows.append(
                {
                    "route_id": rid,
                    "split": split,
                    "station": b.station,
                    "date": b.date,
                    "departure_s": b.departure_s,
                    "n_stops": n - 1,
                    "n_packages": int(b.n_packages.sum()),
                    "stops_with_window": b.quality["stops_with_window"],
                    "null_zones": b.quality["null_zones"],
                    "route_score": b.score,
                    "centroid_lat": float(b.lat[1:].mean()),
                    "centroid_lng": float(b.lng[1:].mean()),
                }
            )
            n_done += 1
            if n_done % 500 == 0:
                print(f"  {n_done} routes ({time.time() - t0:.0f}s)")
            if args.limit and n_done >= args.limit:
                break

    for split, d in arcs.items():
        np.savez_compressed(
            out / f"arcs_{split}.npz",
            X=np.concatenate(d["X"]),
            y=np.concatenate(d["y"]),
            g=np.concatenate(d["g"]),
        )
    with open(out / "route_index.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(index_rows[0]))
        w.writeheader()
        w.writerows(index_rows)
    by_split = Counter(r["split"] for r in index_rows)
    dates_by_split = defaultdict(set)
    for r in index_rows:
        dates_by_split[r["split"]].add(r["date"])
    profile = {
        "routes_in_route_data": len(routes),
        "routes_processed": n_done,
        "routes_rejected": dict(rejected),
        "split_routes": dict(by_split),
        "split_dates": {k: [min(v), max(v), len(v)] for k, v in dates_by_split.items()},
        "stations": station_ids,
        "stops_total": int(sum(r["n_stops"] for r in index_rows)),
        "packages_total": int(sum(r["n_packages"] for r in index_rows)),
        "stops_with_package_window": int(sum(r["stops_with_window"] for r in index_rows)),
        "null_zone_ids": int(quality_tot["null_zones"]),
        "packages_invalid_service_time": int(quality_tot["packages_invalid_service"]),
        "conflicting_windows_dropped": int(quality_tot["conflicting_windows_dropped"]),
        "arcs_sampled": {k: int(sum(len(y) for y in d["y"])) for k, d in arcs.items()},
        "arcs_per_route": args.arcs_per_route,
        "seed": args.seed,
        "route_score_counts": dict(Counter(r["route_score"] for r in index_rows)),
        "stops_per_route": {
            "min": int(min(r["n_stops"] for r in index_rows)),
            "median": float(np.median([r["n_stops"] for r in index_rows])),
            "max": int(max(r["n_stops"] for r in index_rows)),
        },
    }
    (out / "profile.json").write_text(json.dumps(profile, indent=2))
    print(json.dumps(profile, indent=2))
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
