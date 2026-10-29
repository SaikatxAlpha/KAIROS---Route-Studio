"""Seeded stochastic operations model (SYNTHETIC — clearly labelled).

Neither benchmark contains realised per-trip travel or service durations, so
execution variability cannot be calibrated from observed outcomes. KAIROS
therefore uses a transparent multiplicative model whose parameters are
explicit, documented assumptions:

    realised_travel(i, j, s, k) = t_ij * D_s * V_{s,k} * E_{s,ij} * B_{s,ij}
    realised_service(i, s)      = s_i  * G_{s,i}

* ``D_s``     shared day-level congestion factor (correlates all arcs), lognormal
* ``V_{s,k}`` vehicle/driver factor for route k, lognormal
* ``E_{s,ij}`` idiosyncratic traversal noise, lognormal
* ``B_{s,ij}`` estimation error for arcs whose expected time was *estimated*
  by the travel-time model rather than observed (sd from the calibrated model)
* ``G_{s,i}`` service-time factor, gamma with unit mean

All lognormal factors have unit mean, so ``t_ij`` remains the expectation and
the deterministic baseline plans on unbiased inputs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterator

import numpy as np

from kairos.data.schema import Instance

BLOCK = 25  # scenarios per RNG block; fixes the stream independent of batch size
MAX_VEHICLE_FACTORS = 64  # vehicle factors drawn at a fixed width so fleet size never shifts streams


@dataclass(frozen=True)
class UncertaintyConfig:
    day_sigma: float = 0.08
    vehicle_sigma: float = 0.05
    arc_sigma: float = 0.25
    service_cv: float = 0.40
    use_estimation_error: bool = True

    @classmethod
    def preset(cls, level: str) -> "UncertaintyConfig":
        presets = {
            "low": cls(day_sigma=0.04, vehicle_sigma=0.03, arc_sigma=0.12, service_cv=0.20),
            "medium": cls(),
            "high": cls(day_sigma=0.15, vehicle_sigma=0.08, arc_sigma=0.40, service_cv=0.60),
        }
        if level not in presets:
            raise ValueError(f"unknown uncertainty level {level!r}; choose low/medium/high")
        return presets[level]

    def scaled(self, factor: float) -> "UncertaintyConfig":
        """Misspecification helper: multiply every dispersion parameter."""
        return UncertaintyConfig(
            day_sigma=self.day_sigma * factor,
            vehicle_sigma=self.vehicle_sigma * factor,
            arc_sigma=self.arc_sigma * factor,
            service_cv=self.service_cv * factor,
            use_estimation_error=self.use_estimation_error,
        )

    def to_dict(self) -> dict:
        return asdict(self)


def _ln(rng: np.random.Generator, sigma: np.ndarray | float, size) -> np.ndarray:
    sigma = np.asarray(sigma, dtype=float)
    return np.exp(rng.standard_normal(size) * sigma - 0.5 * sigma**2)


def travel_sd(inst: Instance, cfg: UncertaintyConfig) -> np.ndarray:
    """Per-arc standard deviation of realised travel time (planner's view)."""
    var_log = cfg.day_sigma**2 + cfg.vehicle_sigma**2 + cfg.arc_sigma**2
    est = inst.tt_rel_sd**2 if cfg.use_estimation_error else 0.0
    return inst.travel_time * np.sqrt(np.exp(var_log + est) - 1.0)


def service_sd(inst: Instance, cfg: UncertaintyConfig) -> np.ndarray:
    return inst.service * cfg.service_cv


@dataclass
class ScenarioBlock:
    start: int  # index of first scenario in this block
    day: np.ndarray  # (B,)
    vehicle: np.ndarray  # (B, K)
    arc: np.ndarray  # (B, N, N) combined idiosyncratic * estimation factor
    service: np.ndarray  # (B, N)


def iter_scenarios(
    inst: Instance,
    cfg: UncertaintyConfig,
    n_scenarios: int,
    seed: int,
    n_vehicles: int | None = None,
    n_nodes: int | None = None,
) -> Iterator[ScenarioBlock]:
    """Yield reproducible scenario blocks.

    Scenario ``s`` depends only on ``(seed, s)``, so every planner evaluated
    with the same seed sees identical realisations (common random numbers).
    """
    n = n_nodes or inst.n_nodes
    k = n_vehicles or inst.num_vehicles
    rel_sd = inst.tt_rel_sd if inst.tt_rel_sd.shape[0] == n else np.zeros((n, n))
    shape_g = 1.0 / cfg.service_cv**2 if cfg.service_cv > 0 else None
    for b0 in range(0, n_scenarios, BLOCK):
        # Independent child streams per component, so changing one component's
        # shape (e.g. fleet size) never perturbs the others.
        r_day, r_veh, r_arc, r_est, r_svc = (
            np.random.default_rng([seed, b0 // BLOCK, j]) for j in range(5)
        )
        full = BLOCK
        day = _ln(r_day, cfg.day_sigma, full)
        width = max(k, MAX_VEHICLE_FACTORS)
        veh = _ln(r_veh, cfg.vehicle_sigma, (full, width))[:, :k]
        arc = _ln(r_arc, cfg.arc_sigma, (full, n, n)).astype(np.float32)
        if cfg.use_estimation_error and rel_sd.any():
            # Estimation error is a property of the arc, not of the traversal,
            # but it is unknown to the planner: draw once per scenario.
            arc *= _ln(r_est, rel_sd, (full, n, n)).astype(np.float32)
        if shape_g is None:
            svc = np.ones((full, n))
        else:
            svc = r_svc.gamma(shape_g, 1.0 / shape_g, size=(full, n))
        take = min(BLOCK, n_scenarios - b0)
        yield ScenarioBlock(b0, day[:take], veh[:take], arc[:take], svc[:take])
