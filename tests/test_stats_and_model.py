import numpy as np

from kairos.eval.stats import bootstrap_ci, paired_summary, wilcoxon_p
from kairos.uncertainty.traveltime import FEATURES, TravelTimeModel, arc_features, pinball


def test_bootstrap_and_wilcoxon():
    rng = np.random.default_rng(0)
    x = rng.normal(2.0, 1.0, 200)
    lo, hi = bootstrap_ci(x)
    assert lo < x.mean() < hi and lo > 1.5 and hi < 2.5
    assert wilcoxon_p(x) < 1e-6
    assert wilcoxon_p(np.zeros(10)) is None
    assert wilcoxon_p(np.ones(3)) is None
    s = paired_summary(x)
    assert s["n"] == 200 and s["share_positive"] > 0.9


def test_pinball_loss():
    y = np.array([1.0, 2.0, 3.0])
    assert pinball(y, y, 0.5) == 0
    assert pinball(y, y - 1, 0.9) == 0.9  # under-prediction penalised by tau


def test_arc_features_shape_and_zone_flags():
    X = arc_features(
        np.array([34.0, 34.0]), np.array([-118.0, -118.0]), np.array([34.01, 34.0]), np.array([-118.0, -118.01]),
        ["A-1.1A", "A-1.1A"], ["A-1.1A", "B-2.1A"], np.array([True, False]), np.array([False, False]),
        34.0, -118.0, 3, 15.0,
    )
    assert X.shape == (2, len(FEATURES))
    f = {k: i for i, k in enumerate(FEATURES)}
    assert X[0, f["same_zone"]] == 1 and X[1, f["same_zone"]] == 0
    assert X[0, f["hav_km"]] > 1.0 and X[0, f["from_station"]] == 1


def test_conformal_calibration_reaches_nominal_coverage():
    """CQR on synthetic heteroscedastic data: calibrated coverage close to nominal
    on a fresh test set even when the raw quantile model is mis-calibrated."""
    rng = np.random.default_rng(1)

    def make(n):
        X = rng.uniform(0, 1, size=(n, len(FEATURES))).astype(np.float32)
        X[:, FEATURES.index("station_id")] = rng.integers(0, 3, n)
        y = 2 * X[:, 0] + rng.normal(0, 0.1 + 0.5 * X[:, 1], n)
        return X, y.astype(np.float32)

    Xtr, ytr = make(4000)
    Xca, yca = make(3000)
    Xte, yte = make(3000)
    m = TravelTimeModel.fit(Xtr, ytr, {"S": 0}, quantiles=(0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.025, 0.975),
                            num_rounds=40, log=lambda *_: None)
    m.calibrate(Xca, yca)
    ev = m.evaluate(Xte, yte)
    row = next(r for r in ev["coverage"] if r["nominal"] == 0.9)
    assert abs(row["conformal_coverage"] - 0.9) < 0.03
    mean, sd = m.predict_mean_sd(Xte[:5])
    assert mean.shape == (5,) and (sd > 0).all()
