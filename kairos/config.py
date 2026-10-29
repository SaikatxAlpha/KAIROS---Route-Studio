"""Centralised, portable configuration.

All paths derive from the repository root unless overridden through
environment variables, so nothing depends on a machine-specific location.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


DATA_DIR = _path_from_env("KAIROS_DATA_DIR", REPO_ROOT / "data")
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
ARTIFACTS_DIR = _path_from_env("KAIROS_ARTIFACTS_DIR", REPO_ROOT / "artifacts")

SOLOMON_DIR = _path_from_env("KAIROS_SOLOMON_DIR", DATA_DIR / "benchmarks" / "solomon")
AMAZON_RAW_DIR = RAW_DIR / "amazon"
AMAZON_PROCESSED_DIR = PROCESSED_DIR / "amazon"

MODELS_DIR = ARTIFACTS_DIR / "models"
EXPERIMENTS_DIR = ARTIFACTS_DIR / "experiments"

# Solver defaults (seconds). Kept small so the interactive demo stays responsive.
DEFAULT_TIME_LIMIT = float(os.environ.get("KAIROS_TIME_LIMIT", "2.0"))
MAX_TIME_LIMIT = 30.0

# Monte Carlo defaults.
DEFAULT_EVAL_SCENARIOS = 200
DEFAULT_PLANNING_SCENARIOS = 100
MAX_SCENARIOS = 2000

# Seed offsets keep planner (in-sample) and evaluation (out-of-sample)
# scenario streams disjoint for any user-supplied seed.
PLANNING_SEED_OFFSET = 1_000_003
EVALUATION_SEED_OFFSET = 7_000_009
