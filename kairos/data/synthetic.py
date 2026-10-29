"""Deterministic synthetic demonstration instances (SYNTHETIC — labelled).

Used only as an offline fallback and for fast tests; never mixed into
benchmark results.
"""

from __future__ import annotations

import numpy as np

from kairos.data.schema import Instance

PROVENANCE = {
    "dataset": "KAIROS synthetic demonstration instance",
    "observed": [],
    "synthetic": ["all coordinates, demands, windows and service times (seeded generator)",
                  "stochastic variability", "disruptions"],
    "coordinates_note": "Synthetic coordinate space, not geographic.",
}


def make_synthetic(n: int = 40, n_vehicles: int = 6, seed: int = 7, window: float = 60.0) -> Instance:
    rng = np.random.default_rng(seed)
    centers = rng.uniform(15, 85, size=(4, 2))
    pts = centers[rng.integers(0, 4, n)] + rng.normal(0, 9, size=(n, 2))
    coords = np.vstack([[50.0, 50.0], np.clip(pts, 0, 100)])
    d = np.sqrt(((coords[:, None] - coords[None]) ** 2).sum(-1))
    horizon = 480.0
    service = np.concatenate([[0.0], rng.uniform(5, 15, n)])
    # windows anchored so that a direct depot visit is always feasible
    earliest = d[0, 1:]
    centre = rng.uniform(earliest + window / 2, horizon - d[1:, 0] - service[1:] - window / 2)
    tw_e = np.concatenate([[0.0], np.maximum(0.0, centre - window / 2)])
    tw_l = np.concatenate([[horizon], centre + window / 2])
    demand = np.concatenate([[0.0], rng.integers(1, 10, n).astype(float)])
    return Instance(
        id=f"synthetic/demo-{n}-s{seed}",
        name=f"Synthetic demo ({n} stops)",
        source="synthetic",
        coord_system="euclidean",
        coords=coords,
        travel_time=d,
        distance=d,
        service=service,
        tw_early=tw_e,
        tw_late=tw_l,
        demand=demand,
        capacity=60.0,
        num_vehicles=n_vehicles,
        time_unit="min",
        distance_unit="u",
        int_scale=10.0,
        provenance=PROVENANCE,
        meta={"seed": seed, "window": window},
    )
