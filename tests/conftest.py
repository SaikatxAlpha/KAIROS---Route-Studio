import warnings

import pytest

from kairos.data.solomon import load_solomon, subsample
from kairos.data.synthetic import make_synthetic

warnings.filterwarnings("ignore", module="pyvrp")


@pytest.fixture(scope="session")
def syn():
    return make_synthetic(n=20, n_vehicles=5, seed=3)


@pytest.fixture(scope="session")
def r101_small():
    return subsample(load_solomon("R101"), 30, seed=1)


@pytest.fixture(scope="session")
def c101_small():
    return subsample(load_solomon("C101"), 30, seed=2)
