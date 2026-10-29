"""Build merged multi-vehicle Amazon instances from held-out TEST-date routes.

One instance per test-date station-day: a seed route is picked
deterministically and merged with its nearest neighbours (by stop centroid).
Note: the chronologically last dates in the dataset only contain routes from
four stations (DLA9, DSE2, DSE4, DSE5), so the test instances cover Los
Angeles and Seattle only. Cross-route travel times come from the trained
travel-time model (never trained on test dates).

Outputs data/processed/amazon/instances/*.json.gz (all) and copies a small
demo set to data/demo/amazon/ (shipped with the repository, CC BY-NC 4.0).
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kairos.config import AMAZON_PROCESSED_DIR, DATA_DIR, MODELS_DIR  # noqa: E402
from kairos.data.amazon import MergeConfig, load_bundle, merge_routes, stable_hash  # noqa: E402
from kairos.data.registry import save_instance  # noqa: E402

DEMO = {"DLA9-2018-08-24", "DSE4-2018-08-24", "DSE5-2018-08-23"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes-per-instance", type=int, default=2)
    ap.add_argument("--max-stops", type=int, default=320, help="skip merges larger than this")
    args = ap.parse_args()

    from kairos.uncertainty.traveltime import TravelTimeModel

    model_dir = MODELS_DIR / "traveltime"
    estimator = TravelTimeModel.load(model_dir) if (model_dir / "model.json").exists() else None
    if estimator is None:
        print("WARNING: travel-time model missing; using haversine speed-fit fallback")

    rows = list(csv.DictReader(open(AMAZON_PROCESSED_DIR / "route_index.csv")))
    test = [r for r in rows if r["split"] == "test"]
    by_sd: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in test:
        by_sd[(r["station"], r["date"])].append(r)

    out_dir = AMAZON_PROCESSED_DIR / "instances"
    out_dir.mkdir(parents=True, exist_ok=True)
    demo_dir = DATA_DIR / "demo" / "amazon"
    demo_dir.mkdir(parents=True, exist_ok=True)
    built = []
    for station, date in sorted(by_sd):
        n = len(by_sd[(station, date)])
        if n < args.routes_per_instance:
            print(f"skip {station} {date}: only {n} test routes")
            continue
        routes = sorted(by_sd[(station, date)], key=lambda r: r["route_id"])
        seed = routes[stable_hash(station + date) % len(routes)]
        c0 = np.array([float(seed["centroid_lat"]), float(seed["centroid_lng"])])
        others = sorted(
            (r for r in routes if r is not seed),
            key=lambda r: np.hypot(float(r["centroid_lat"]) - c0[0], float(r["centroid_lng"]) - c0[1]),
        )
        chosen = [seed]
        for r in others:
            if len(chosen) == args.routes_per_instance:
                break
            if sum(int(x["n_stops"]) for x in chosen) + int(r["n_stops"]) <= args.max_stops:
                chosen.append(r)
        if len(chosen) < args.routes_per_instance:
            print(f"skip {station} {date}: cannot merge within {args.max_stops} stops")
            continue
        bundles = [load_bundle(AMAZON_PROCESSED_DIR / "routes" / f"{r['route_id']}.json.gz") for r in chosen]
        inst = merge_routes(bundles, estimator=estimator, cfg=MergeConfig(),
                            instance_id=f"amazon/{station}-{date}")
        path = save_instance(inst, out_dir / f"{station}-{date}.json.gz")
        if f"{station}-{date}" in DEMO:
            shutil.copy(path, demo_dir / path.name)
        built.append(inst)
        print(f"{inst.id}: {inst.n_clients} stops, {inst.num_vehicles} vehicles, "
              f"{inst.meta['share_tt_observed']:.0%} arcs observed, {inst.meta['n_observed_windows']} observed windows")
    print(f"built {len(built)} instances")


if __name__ == "__main__":
    main()
