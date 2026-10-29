"""Paired statistics for method comparisons."""

from __future__ import annotations

from typing import Any

import numpy as np


def bootstrap_ci(x: np.ndarray, n_boot: int = 5000, level: float = 0.95, seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        m = float(x.mean()) if len(x) else float("nan")
        return (m, m)
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(1)
    a = (1 - level) / 2
    return float(np.quantile(means, a)), float(np.quantile(means, 1 - a))


def wilcoxon_p(x: np.ndarray) -> float | None:
    """Two-sided Wilcoxon signed-rank p-value for paired differences."""
    from scipy.stats import wilcoxon

    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 6 or np.allclose(x, 0):
        return None
    try:
        return float(wilcoxon(x, zero_method="zsplit").pvalue)
    except ValueError:
        return None


def paired_summary(diff: np.ndarray, seed: int = 0) -> dict[str, Any]:
    diff = np.asarray(diff, dtype=float)
    lo, hi = bootstrap_ci(diff, seed=seed)
    return {
        "n": int(np.isfinite(diff).sum()),
        "mean": float(np.nanmean(diff)) if len(diff) else None,
        "median": float(np.nanmedian(diff)) if len(diff) else None,
        "ci95": [lo, hi],
        "wilcoxon_p": wilcoxon_p(diff),
        "share_positive": float(np.mean(diff > 0)) if len(diff) else None,
    }
