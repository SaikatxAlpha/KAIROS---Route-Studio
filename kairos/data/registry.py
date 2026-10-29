"""Catalogue of every instance the application can load.

Sources:
* ``solomon/<NAME>``   56 Solomon VRPTW benchmark instances (shipped).
* ``amazon/<...>``     merged Amazon station-day instances built by
                       ``scripts/build_amazon_instances.py``; a small demo set
                       is shipped in ``data/demo/amazon`` (CC BY-NC 4.0).
* ``synthetic/<...>``  deterministic synthetic fallback.
"""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from kairos.config import DATA_DIR, PROCESSED_DIR, SOLOMON_DIR
from kairos.data.schema import Instance
from kairos.data.solomon import PROVENANCE as SOLOMON_PROVENANCE
from kairos.data.solomon import list_solomon, load_solomon
from kairos.data.synthetic import PROVENANCE as SYN_PROVENANCE
from kairos.data.synthetic import make_synthetic

AMAZON_DIRS = [DATA_DIR / "demo" / "amazon", PROCESSED_DIR / "amazon" / "instances"]
SYNTHETIC_IDS = {"synthetic/demo-40-s7": (40, 6, 7), "synthetic/demo-80-s11": (80, 10, 11)}


def save_instance(inst: Instance, path: Path) -> Path:
    """Serialise an instance (with matrices) to gzipped JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    d = {
        "id": inst.id,
        "name": inst.name,
        "source": inst.source,
        "coord_system": inst.coord_system,
        "coords": inst.coords.round(6).tolist(),
        "travel_time": inst.travel_time.round(1).tolist(),
        "distance": inst.distance.round(1).tolist(),
        "service": inst.service.tolist(),
        "tw_early": inst.tw_early.tolist(),
        "tw_late": inst.tw_late.tolist(),
        "demand": inst.demand.round(3).tolist(),
        "capacity": inst.capacity,
        "num_vehicles": inst.num_vehicles,
        "time_unit": inst.time_unit,
        "distance_unit": inst.distance_unit,
        "int_scale": inst.int_scale,
        "vehicle_fixed_cost": inst.vehicle_fixed_cost,
        "has_tw": inst.has_tw.tolist(),
        "tt_observed": inst.tt_observed.astype(np.uint8).tolist(),
        "tt_rel_sd": inst.tt_rel_sd.round(4).tolist(),
        "stop_ids": inst.stop_ids,
        "zones": inst.zones,
        "provenance": inst.provenance,
        "meta": inst.meta,
    }
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(d, f)
    return path


def read_instance(path: Path) -> Instance:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        d = json.load(f)
    return Instance(
        id=d["id"],
        name=d["name"],
        source=d["source"],
        coord_system=d["coord_system"],
        coords=np.asarray(d["coords"]),
        travel_time=np.asarray(d["travel_time"]),
        distance=np.asarray(d["distance"]),
        service=np.asarray(d["service"]),
        tw_early=np.asarray(d["tw_early"]),
        tw_late=np.asarray(d["tw_late"]),
        demand=np.asarray(d["demand"]),
        capacity=d["capacity"],
        num_vehicles=d["num_vehicles"],
        time_unit=d["time_unit"],
        distance_unit=d["distance_unit"],
        int_scale=d["int_scale"],
        vehicle_fixed_cost=d.get("vehicle_fixed_cost", 0.0),
        has_tw=np.asarray(d["has_tw"], dtype=bool),
        tt_observed=np.asarray(d["tt_observed"], dtype=bool),
        tt_rel_sd=np.asarray(d["tt_rel_sd"]),
        stop_ids=d["stop_ids"],
        zones=d["zones"],
        provenance=d["provenance"],
        meta=d["meta"],
    )


def _amazon_files() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for directory in AMAZON_DIRS:
        if not directory.exists():
            continue
        for p in sorted(directory.glob("*.json.gz")):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                head = f.read(400)
            key = head.split('"id": "', 1)[1].split('"', 1)[0] if '"id": "' in head else p.stem
            found.setdefault(key, p)
    return found


def datasets() -> list[dict[str, Any]]:
    amazon = _amazon_files()
    out = [
        {
            "source": "amazon",
            "label": "Amazon Last Mile (merged station-days)",
            "kind": "Observed benchmark + model estimates + labelled synthetic windows",
            "n_instances": len(amazon),
            "available": bool(amazon),
            "provenance": {
                "dataset": "Amazon Last Mile Routing Research Challenge 2021",
                "license": "CC BY-NC 4.0",
            },
        },
        {
            "source": "solomon",
            "label": "Solomon VRPTW (100 customers)",
            "kind": "Observed public benchmark",
            "n_instances": len(list_solomon(SOLOMON_DIR)),
            "available": SOLOMON_DIR.exists(),
            "provenance": SOLOMON_PROVENANCE,
        },
        {
            "source": "synthetic",
            "label": "Synthetic demo",
            "kind": "Synthetic (seeded generator)",
            "n_instances": len(SYNTHETIC_IDS),
            "available": True,
            "provenance": SYN_PROVENANCE,
        },
    ]
    return out


def list_instances(source: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if source in (None, "amazon"):
        for iid in _amazon_files():
            rows.append(load_instance(iid).summary())
    if source in (None, "solomon"):
        for name in list_solomon(SOLOMON_DIR):
            rows.append(load_instance(f"solomon/{name}").summary())
    if source in (None, "synthetic"):
        for iid in SYNTHETIC_IDS:
            rows.append(load_instance(iid).summary())
    return rows


@lru_cache(maxsize=128)
def load_instance(instance_id: str) -> Instance:
    if instance_id.startswith("solomon/"):
        return load_solomon(instance_id.split("/", 1)[1])
    if instance_id in SYNTHETIC_IDS:
        n, k, seed = SYNTHETIC_IDS[instance_id]
        return make_synthetic(n, k, seed)
    if instance_id.startswith("amazon/"):
        files = _amazon_files()
        if instance_id in files:
            return read_instance(files[instance_id])
    raise KeyError(f"unknown instance {instance_id!r}")
