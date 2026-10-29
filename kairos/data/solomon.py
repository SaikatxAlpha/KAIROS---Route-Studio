"""Loader for the Solomon (1987) VRPTW benchmark (100-customer instances).

Distances and travel times are Euclidean in benchmark units (the standard
convention: one distance unit takes one time unit to travel).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from kairos.config import SOLOMON_DIR
from kairos.data.schema import Instance

PROVENANCE = {
    "dataset": "Solomon VRPTW benchmark (100 customers)",
    "reference": "M. M. Solomon (1987). Algorithms for the vehicle routing and scheduling "
    "problems with time window constraints. Operations Research 35(2):254-265.",
    "origin": "Public benchmark; files mirrored from the SINTEF TOP VRPTW collection.",
    "observed": ["coordinates", "demands", "time windows", "service times", "fleet size", "capacity"],
    "derived": ["Euclidean travel times (benchmark convention)"],
    "synthetic": ["stochastic travel/service variability (KAIROS scenario model)", "disruptions"],
    "coordinates_note": "Abstract benchmark coordinate space, not geographic.",
}


class SolomonParseError(ValueError):
    pass


def parse_solomon(text: str, name: str) -> Instance:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    try:
        v_idx = next(i for i, ln in enumerate(lines) if ln.upper().startswith("VEHICLE"))
        num_vehicles, capacity = (int(float(t)) for t in lines[v_idx + 2].split()[:2])
        c_idx = next(i for i, ln in enumerate(lines) if ln.upper().startswith("CUSTOMER"))
    except (StopIteration, ValueError, IndexError) as exc:
        raise SolomonParseError(f"{name}: malformed header") from exc

    rows = []
    for ln in lines[c_idx + 1 :]:
        parts = ln.split()
        if len(parts) != 7:
            continue
        try:
            rows.append([float(p) for p in parts])
        except ValueError:
            continue  # column header line
    if len(rows) < 2:
        raise SolomonParseError(f"{name}: no customer rows")
    arr = np.asarray(rows)
    if arr[0, 0] != 0:
        raise SolomonParseError(f"{name}: first row must be the depot (id 0)")

    coords = arr[:, 1:3]
    diff = coords[:, None, :] - coords[None, :, :]
    dist = np.sqrt((diff**2).sum(-1))
    n = len(arr)
    family = "".join(c for c in name if c.isalpha())
    series = name[len(family)]  # "1" = short horizon / tight windows, "2" = long horizon
    return Instance(
        id=f"solomon/{name}",
        name=f"Solomon {name}",
        source="solomon",
        coord_system="euclidean",
        coords=coords,
        travel_time=dist,
        distance=dist,
        service=arr[:, 6],
        tw_early=arr[:, 4],
        tw_late=arr[:, 5],
        demand=arr[:, 3],
        capacity=float(capacity),
        num_vehicles=num_vehicles,
        time_unit="u",
        distance_unit="u",
        int_scale=10.0,
        stop_ids=["depot"] + [f"C{int(c):03d}" for c in arr[1:, 0]],
        provenance=PROVENANCE,
        meta={
            "family": family,
            "group": family + series,
            "tight_windows": series == "1",
            "n": n - 1,
        },
    )


def list_solomon(directory: Path = SOLOMON_DIR) -> list[str]:
    return sorted(p.stem.upper() for p in directory.glob("*.txt"))


def load_solomon(name: str, directory: Path = SOLOMON_DIR) -> Instance:
    name = name.upper()
    path = directory / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Solomon instance {name} not found in {directory}")
    return parse_solomon(path.read_text(), name)


def subsample(inst: Instance, n: int, seed: int = 0) -> Instance:
    """Deterministic sub-instance with ``n`` customers (used for fast tests)."""
    rng = np.random.default_rng(seed)
    keep = np.sort(rng.choice(np.arange(1, inst.n_nodes), size=n, replace=False))
    idx = np.concatenate([[0], keep])
    return Instance(
        id=f"{inst.id}-n{n}-s{seed}",
        name=f"{inst.name} (n={n})",
        source=inst.source,
        coord_system=inst.coord_system,
        coords=inst.coords[idx],
        travel_time=inst.travel_time[np.ix_(idx, idx)],
        distance=inst.distance[np.ix_(idx, idx)],
        service=inst.service[idx],
        tw_early=inst.tw_early[idx],
        tw_late=inst.tw_late[idx],
        demand=inst.demand[idx],
        capacity=inst.capacity,
        num_vehicles=inst.num_vehicles,
        time_unit=inst.time_unit,
        distance_unit=inst.distance_unit,
        int_scale=inst.int_scale,
        has_tw=inst.has_tw[idx],
        stop_ids=[inst.stop_ids[i] for i in idx],
        zones=[inst.zones[i] for i in idx],
        provenance=inst.provenance,
        meta={**inst.meta, "subsample_of": inst.id, "n": n},
    )
