"""Travel-time estimation with calibrated uncertainty (REAL outcome data).

Target: the Amazon dataset's observed average travel time between two stops
(seconds). Features are geometric and contextual only, so the model can
estimate travel times for stop pairs that were never observed together —
cross-route pairs in merged instances and newly released urgent orders.

Method:
* LightGBM quantile regression on log travel time for several quantile
  levels (one model per level).
* Conformalized quantile regression (Romano, Patterson & Candès, 2019) on a
  *temporally held-out* calibration block of dates: for each nominal level,
  the interval [q_lo, q_hi] is widened (or narrowed) by the finite-sample
  (1 - alpha)(1 + 1/n) quantile of the conformity scores.
* Evaluation on a later, disjoint block of test dates: empirical coverage,
  interval width, pinball loss, MAE/MAPE, against a log-log haversine
  speed baseline.

Caveats (reported with the results): arcs within a route are not independent,
so the calibration guarantee holds marginally over arcs only under
exchangeability between the calibration and test blocks; the interval is for
estimating an *average* travel time, not day-to-day variability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

FEATURES = [
    "hav_km",
    "log_hav",
    "dx_km",
    "dy_km",
    "bear_sin",
    "bear_cos",
    "same_zone",
    "same_super",
    "same_letter",
    "from_station",
    "to_station",
    "station_id",
    "dep_hour",
    "ox_km",
    "oy_km",
    "tx_km",
    "ty_km",
]
CATEGORICAL = ["station_id"]
QUANTILES = (0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.975)
LEVELS = (0.5, 0.8, 0.9, 0.95)  # nominal central interval coverages
KM_PER_DEG_LAT = 111.32


def zone_parts(z: str | None) -> tuple[str, str, str]:
    """'A-1.2D' -> ('A-1.2D', 'A-1', 'A')."""
    if not z:
        return ("", "", "")
    sup = z.split(".")[0]
    return (z, sup, z[:1])


def arc_features(
    lat_o: np.ndarray,
    lng_o: np.ndarray,
    lat_d: np.ndarray,
    lng_d: np.ndarray,
    zone_o: list,
    zone_d: list,
    from_station: np.ndarray,
    to_station: np.ndarray,
    station_lat: float,
    station_lng: float,
    station_id: int,
    dep_hour: float,
) -> np.ndarray:
    from kairos.data.amazon import haversine_km

    lat_o, lng_o, lat_d, lng_d = (np.asarray(a, dtype=float) for a in (lat_o, lng_o, lat_d, lng_d))
    coslat = np.cos(np.radians(station_lat))
    hav = haversine_km(lat_o, lng_o, lat_d, lng_d)
    dx = (lng_d - lng_o) * KM_PER_DEG_LAT * coslat
    dy = (lat_d - lat_o) * KM_PER_DEG_LAT
    bear = np.arctan2(dy, dx)
    zo = [zone_parts(z) for z in zone_o]
    zd = [zone_parts(z) for z in zone_d]
    same = np.array([[a[k] == b[k] and a[k] != "" for k in range(3)] for a, b in zip(zo, zd)], dtype=float)
    if len(same) == 0:
        same = np.zeros((0, 3))
    m = len(hav)
    X = np.column_stack(
        [
            hav,
            np.log(hav + 0.01),
            dx,
            dy,
            np.sin(bear),
            np.cos(bear),
            same[:, 0],
            same[:, 1],
            same[:, 2],
            np.asarray(from_station, dtype=float),
            np.asarray(to_station, dtype=float),
            np.full(m, station_id, dtype=float),
            np.full(m, dep_hour, dtype=float),
            (lng_o - station_lng) * KM_PER_DEG_LAT * coslat,
            (lat_o - station_lat) * KM_PER_DEG_LAT,
            (lng_d - station_lng) * KM_PER_DEG_LAT * coslat,
            (lat_d - station_lat) * KM_PER_DEG_LAT,
        ]
    )
    return X.astype(np.float32)


def pinball(y: np.ndarray, q: np.ndarray, tau: float) -> float:
    d = y - q
    return float(np.mean(np.maximum(tau * d, (tau - 1) * d)))


@dataclass
class TravelTimeModel:
    station_ids: dict[str, int]
    boosters: dict[float, Any] = field(default_factory=dict)  # quantile -> lightgbm.Booster
    conformal: dict[float, float] = field(default_factory=dict)  # level -> additive log-scale correction
    params: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ fit
    @classmethod
    def fit(
        cls,
        X: np.ndarray,
        y_log: np.ndarray,
        station_ids: dict[str, int],
        quantiles: tuple[float, ...] = QUANTILES,
        num_rounds: int = 400,
        seed: int = 0,
        log=print,
    ) -> "TravelTimeModel":
        import lightgbm as lgb

        params = {
            "objective": "quantile",
            "learning_rate": 0.08,
            "num_leaves": 63,
            "min_data_in_leaf": 200,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.8,
            "bagging_freq": 1,
            "seed": seed,
            "verbose": -1,
            "num_threads": 0,
        }
        model = cls(station_ids=station_ids, params={**params, "num_rounds": num_rounds})
        ds = lgb.Dataset(X, y_log, feature_name=FEATURES, categorical_feature=CATEGORICAL, free_raw_data=False)
        for q in quantiles:
            log(f"  training quantile {q}")
            model.boosters[q] = lgb.train({**params, "alpha": q}, ds, num_boost_round=num_rounds)
        return model

    def predict_quantiles(self, X: np.ndarray) -> dict[float, np.ndarray]:
        raw = {q: b.predict(X) for q, b in self.boosters.items()}
        # enforce monotone quantiles (rearrangement)
        qs = sorted(raw)
        stacked = np.sort(np.vstack([raw[q] for q in qs]), axis=0)
        return {q: stacked[i] for i, q in enumerate(qs)}

    def interval(self, qpred: dict[float, np.ndarray], level: float, conformal: bool = True):
        a = (1 - level) / 2
        lo, hi = qpred[round(a, 4)], qpred[round(1 - a, 4)]
        c = self.conformal.get(level, 0.0) if conformal else 0.0
        return lo - c, hi + c

    def calibrate(self, X: np.ndarray, y_log: np.ndarray) -> None:
        qpred = self.predict_quantiles(X)
        n = len(y_log)
        for level in LEVELS:
            lo, hi = self.interval(qpred, level, conformal=False)
            scores = np.maximum(lo - y_log, y_log - hi)
            k = min(1.0, (1 - (1 - level)) * (1 + 1 / n))
            self.conformal[level] = float(np.quantile(scores, k, method="higher"))

    # ------------------------------------------------------------- evaluate
    def evaluate(self, X: np.ndarray, y_log: np.ndarray, groups: np.ndarray | None = None) -> dict[str, Any]:
        qpred = self.predict_quantiles(X)
        y = np.exp(y_log)
        med = np.exp(qpred[0.5])
        out: dict[str, Any] = {
            "n_arcs": int(len(y)),
            "mae_s": float(np.mean(np.abs(med - y))),
            "mape": float(np.mean(np.abs(med - y) / np.maximum(y, 1.0))),
            "median_ape": float(np.median(np.abs(med - y) / np.maximum(y, 1.0))),
            "pinball_log": {str(q): pinball(y_log, p, q) for q, p in qpred.items()},
            "coverage": [],
        }
        for level in LEVELS:
            row = {"nominal": level}
            for tag, conf in (("raw", False), ("conformal", True)):
                lo, hi = self.interval(qpred, level, conformal=conf)
                inside = (y_log >= lo) & (y_log <= hi)
                row[f"{tag}_coverage"] = float(inside.mean())
                row[f"{tag}_rel_width"] = float(np.median(np.exp(hi) / np.exp(lo) - 1.0))
                if groups is not None and conf:
                    _, inv = np.unique(groups, return_inverse=True)
                    per = np.bincount(inv, weights=inside) / np.bincount(inv)
                    row["route_coverage_p10"] = float(np.quantile(per, 0.1))
                    row["route_coverage_p90"] = float(np.quantile(per, 0.9))
            out["coverage"].append(row)
        return out

    # ------------------------------------------------------------- inference
    def predict_mean_sd(self, X: np.ndarray, level: float = 0.9) -> tuple[np.ndarray, np.ndarray]:
        """Expected travel time (s) and log-scale sd implied by the calibrated interval."""
        qpred = self.predict_quantiles(X)
        lo, hi = self.interval(qpred, level, conformal=True)
        z = {0.5: 0.674, 0.8: 1.2816, 0.9: 1.6449, 0.95: 1.96}[level]
        sd = np.maximum((hi - lo) / (2 * z), 1e-3)
        mean = np.exp(qpred[0.5] + 0.5 * sd**2)
        return mean, sd

    def predict_pairs(self, lat, lng, zones, station: str, t0_s: float, mask: np.ndarray):
        """Predict travel times for the masked (i, j) pairs of a node set (node 0 = station)."""
        ii, jj = np.nonzero(mask)
        X = arc_features(
            lat[ii],
            lng[ii],
            lat[jj],
            lng[jj],
            [zones[i] for i in ii],
            [zones[j] for j in jj],
            ii == 0,
            jj == 0,
            float(lat[0]),
            float(lng[0]),
            self.station_ids.get(station, -1),
            (t0_s / 3600.0) % 24,
        )
        return self.predict_mean_sd(X)

    def urgent_estimator(self, station: str, t0_s: float):
        """Estimator for a new stop at ``loc`` (lng, lat) in an Amazon instance."""

        def estimate(inst, loc):
            lat = inst.coords[:, 1]
            lng = inst.coords[:, 0]
            n = len(lat)
            new_lat = np.full(n, loc[1])
            new_lng = np.full(n, loc[0])
            sid = self.station_ids.get(station, -1)
            hour = (t0_s / 3600.0) % 24
            zones = [None] * n
            out_X = arc_features(new_lat, new_lng, lat, lng, zones, inst.zones, np.zeros(n), np.arange(n) == 0,
                                 float(lat[0]), float(lng[0]), sid, hour)
            in_X = arc_features(lat, lng, new_lat, new_lng, inst.zones, zones, np.arange(n) == 0, np.zeros(n),
                                float(lat[0]), float(lng[0]), sid, hour)
            tt_out, sd_out = self.predict_mean_sd(out_X)
            tt_in, sd_in = self.predict_mean_sd(in_X)
            return tt_out, tt_in, sd_out, sd_in

        return estimate

    # ----------------------------------------------------------- persistence
    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for q, b in self.boosters.items():
            b.save_model(str(directory / f"q{q:.3f}.txt"))
        meta = {
            "station_ids": self.station_ids,
            "quantiles": sorted(self.boosters),
            "conformal": {str(k): v for k, v in self.conformal.items()},
            "params": self.params,
            "features": FEATURES,
            "report": self.report,
        }
        (directory / "model.json").write_text(json.dumps(meta, indent=2))

    @classmethod
    def load(cls, directory: Path) -> "TravelTimeModel":
        import lightgbm as lgb

        meta = json.loads((directory / "model.json").read_text())
        model = cls(
            station_ids=meta["station_ids"],
            conformal={float(k): v for k, v in meta["conformal"].items()},
            params=meta["params"],
            report=meta.get("report", {}),
        )
        for q in meta["quantiles"]:
            model.boosters[float(q)] = lgb.Booster(model_file=str(directory / f"q{q:.3f}.txt"))
        return model


def speed_baseline(X_train, y_train, X_test) -> np.ndarray:
    """Per-station log-log regression of travel time on haversine distance."""
    out = np.empty(len(X_test))
    li = FEATURES.index("log_hav")
    si = FEATURES.index("station_id")
    glob = np.polyfit(X_train[:, li], y_train, 1)
    for s in np.unique(X_test[:, si]):
        mt = X_train[:, si] == s
        coef = np.polyfit(X_train[mt, li], y_train[mt], 1) if mt.sum() > 100 else glob
        me = X_test[:, si] == s
        out[me] = np.polyval(coef, X_test[me, li])
    return out
