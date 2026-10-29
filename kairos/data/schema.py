"""Canonical routing-instance representation used by every KAIROS component.

Node 0 is always the depot; nodes 1..n are delivery stops. All times are in
the instance's native ``time_unit`` (benchmark units for Solomon, seconds for
Amazon-derived instances). ``int_scale`` converts native values to the
integers required by PyVRP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


class InstanceValidationError(ValueError):
    """Raised when an instance violates the schema invariants."""


@dataclass
class Instance:
    id: str
    name: str
    source: str  # "solomon" | "amazon" | "synthetic"
    coord_system: str  # "euclidean" | "wgs84" (x = lng, y = lat)
    coords: np.ndarray  # (N, 2)
    travel_time: np.ndarray  # (N, N) expected travel time
    distance: np.ndarray  # (N, N) travel cost used as the routing objective
    service: np.ndarray  # (N,) planned service duration
    tw_early: np.ndarray  # (N,)
    tw_late: np.ndarray  # (N,) latest service start; depot entry = shift end
    demand: np.ndarray  # (N,)
    capacity: float
    num_vehicles: int
    time_unit: str = "u"
    distance_unit: str = "u"
    int_scale: float = 1.0
    vehicle_fixed_cost: float = 0.0  # cost of dispatching a vehicle, in distance units
    has_tw: np.ndarray | None = None  # (N,) bool: stop has a promised window
    tt_observed: np.ndarray | None = None  # (N, N) bool: travel time observed in source
    tt_rel_sd: np.ndarray | None = None  # (N, N) relative estimation sd (0 if observed)
    stop_ids: list[str] = field(default_factory=list)
    zones: list[str | None] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = len(self.coords)
        self.coords = np.asarray(self.coords, dtype=float)
        self.travel_time = np.asarray(self.travel_time, dtype=float)
        self.distance = np.asarray(self.distance, dtype=float)
        for name in ("service", "tw_early", "tw_late", "demand"):
            setattr(self, name, np.asarray(getattr(self, name), dtype=float))
        if self.has_tw is None:
            self.has_tw = np.ones(n, dtype=bool)
            self.has_tw[0] = False
        if self.tt_observed is None:
            self.tt_observed = np.ones((n, n), dtype=bool)
        if self.tt_rel_sd is None:
            self.tt_rel_sd = np.zeros((n, n), dtype=float)
        if not self.stop_ids:
            self.stop_ids = ["depot"] + [f"S{i:03d}" for i in range(1, n)]
        if not self.zones:
            self.zones = [None] * n
        validate_instance(self)

    @property
    def n_nodes(self) -> int:
        return len(self.coords)

    @property
    def n_clients(self) -> int:
        return len(self.coords) - 1

    @property
    def horizon(self) -> float:
        return float(self.tw_late[0])

    def summary(self) -> dict[str, Any]:
        windows = self.tw_late[1:] - self.tw_early[1:]
        has_tw = self.has_tw[1:]
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "coord_system": self.coord_system,
            "n_clients": self.n_clients,
            "num_vehicles": self.num_vehicles,
            "capacity": self.capacity,
            "total_demand": float(self.demand.sum()),
            "horizon": self.horizon,
            "time_unit": self.time_unit,
            "distance_unit": self.distance_unit,
            "n_time_windows": int(has_tw.sum()),
            "median_window": float(np.median(windows[has_tw])) if has_tw.any() else None,
            "share_tt_observed": float(self.tt_observed.mean()),
            "vehicle_fixed_cost": self.vehicle_fixed_cost,
            "meta": self.meta,
        }


def validate_instance(inst: Instance) -> None:
    """Check structural and semantic invariants; raise on violation."""
    n = len(inst.coords)
    errors: list[str] = []
    if n < 2:
        errors.append("instance needs a depot and at least one stop")
    if inst.coords.shape != (n, 2):
        errors.append(f"coords must be (N,2), got {inst.coords.shape}")
    for name in ("travel_time", "distance"):
        m = getattr(inst, name)
        if m.shape != (n, n):
            errors.append(f"{name} must be ({n},{n}), got {m.shape}")
        elif not np.all(np.isfinite(m)):
            errors.append(f"{name} contains non-finite values")
        elif (m < 0).any():
            errors.append(f"{name} contains negative values")
    for name in ("service", "tw_early", "tw_late", "demand"):
        v = getattr(inst, name)
        if v.shape != (n,):
            errors.append(f"{name} must have length {n}, got {v.shape}")
        elif not np.all(np.isfinite(v)):
            errors.append(f"{name} contains non-finite values")
    if not errors:
        if (inst.tw_early > inst.tw_late).any():
            bad = np.flatnonzero(inst.tw_early > inst.tw_late)[:5].tolist()
            errors.append(f"tw_early > tw_late at nodes {bad}")
        if (inst.service < 0).any():
            errors.append("negative service durations")
        if (inst.demand < 0).any():
            errors.append("negative demand")
        if inst.capacity <= 0:
            errors.append("capacity must be positive")
        if inst.num_vehicles < 1:
            errors.append("at least one vehicle required")
        if inst.demand[1:].max(initial=0) > inst.capacity:
            errors.append("a single stop's demand exceeds vehicle capacity")
    if inst.coord_system not in ("euclidean", "wgs84"):
        errors.append(f"unknown coord_system {inst.coord_system!r}")
    if len(inst.stop_ids) != n:
        errors.append("stop_ids length mismatch")
    if errors:
        raise InstanceValidationError(f"{inst.id}: " + "; ".join(errors))


def instance_to_dict(inst: Instance, include_matrices: bool = False) -> dict[str, Any]:
    """JSON-friendly representation for the API (matrices omitted by default)."""
    stops = []
    for i in range(inst.n_nodes):
        stops.append(
            {
                "index": i,
                "id": inst.stop_ids[i],
                "x": float(inst.coords[i, 0]),
                "y": float(inst.coords[i, 1]),
                "is_depot": i == 0,
                "service": float(inst.service[i]),
                "tw_early": float(inst.tw_early[i]),
                "tw_late": float(inst.tw_late[i]),
                "has_tw": bool(inst.has_tw[i]),
                "demand": float(inst.demand[i]),
                "zone": inst.zones[i],
            }
        )
    out: dict[str, Any] = {
        "summary": inst.summary(),
        "stops": stops,
        "provenance": inst.provenance,
    }
    if include_matrices:
        out["travel_time"] = inst.travel_time.round(3).tolist()
        out["distance"] = inst.distance.round(3).tolist()
    return out
