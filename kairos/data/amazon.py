"""Amazon Last Mile Routing Research Challenge (2021) ingestion.

What the dataset contains (verified against the official data-structure
documentation and the files themselves):

* ``route_data.json``   station, date, departure time (UTC), vehicle capacity,
                        stop lat/lng (WGS84), stop type, zone id, route score
* ``package_data.json`` per-package scan status, time window (mostly NaN —
                        about 6.5% of stops carry a window, median width 8 h),
                        planned service time, dimensions
* ``travel_times.json`` per-route stop-to-stop matrix of *average historically
                        realised* travel times (seconds)
* ``actual_sequences.json`` the stop order the driver actually followed

What it does NOT contain: realised per-trip travel or service durations,
arrival timestamps, live traffic, breakdowns, or road distances. KAIROS uses it
for real geography, observed average travel times, planned service times,
real package windows, fleet capacity and observed driver sequences, and is
explicit about everything that is model-estimated or synthetic.

Licence: CC BY-NC 4.0. Citation: Merchán, D., Arora, J., Pachon, J., Konduri,
K., Winkenbach, M., Parks, S., Noszek, J. (2022). 2021 Amazon Last Mile Routing
Research Challenge: Data Set. Transportation Science.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from kairos.config import AMAZON_PROCESSED_DIR
from kairos.data.schema import Instance

CITATION = (
    "Merchan, D., Arora, J., Pachon, J., Konduri, K., Winkenbach, M., Parks, S., Noszek, J. (2022). "
    "2021 Amazon Last Mile Routing Research Challenge: Data Set. Transportation Science. "
    "Accessed from https://registry.opendata.aws/amazon-last-mile-challenges"
)
LICENSE = "CC BY-NC 4.0 (https://creativecommons.org/licenses/by-nc/4.0/)"

# UTC offsets during the data period (July-August 2018, daylight saving time).
CITY_UTC_OFFSET_H = {"LA": -7, "SE": -7, "CH": -5, "AU": -5, "BO": -4}
CITY_NAME = {"LA": "Los Angeles", "SE": "Seattle", "CH": "Chicago", "AU": "Austin", "BO": "Boston"}

SPLIT_FRACTIONS = (0.70, 0.15, 0.15)  # train / calibration / test, by date


class AmazonSchemaError(ValueError):
    pass


@dataclass
class RouteBundle:
    """Validated, compact representation of one historical route."""

    route_id: str
    station: str
    date: str
    departure_s: float  # seconds after 00:00 UTC
    capacity_l: float
    score: str | None
    stop_ids: list[str]  # index 0 = station
    lat: np.ndarray
    lng: np.ndarray
    zones: list[str | None]
    travel_time: np.ndarray  # (n, n) seconds, observed averages
    service_s: np.ndarray  # planned service per stop (sum over packages)
    volume_l: np.ndarray
    n_packages: np.ndarray
    tw_start_s: np.ndarray  # real package window (intersection), NaN if none; s after 00:00 UTC of route date
    tw_end_s: np.ndarray
    actual_order: list[int]  # stop indices in observed visiting order (starts at station)
    quality: dict[str, Any] = field(default_factory=dict)

    @property
    def city(self) -> str:
        return self.station[1:3]


def date_split(dates: list[str]) -> dict[str, str]:
    """Deterministic temporal split: earliest 70% of dates train, next 15%
    calibration, latest 15% test. Prevents same-day leakage between splits."""
    uniq = sorted(set(dates))
    n = len(uniq)
    n_tr = int(round(n * SPLIT_FRACTIONS[0]))
    n_ca = int(round(n * SPLIT_FRACTIONS[1]))
    out = {}
    for i, d in enumerate(uniq):
        out[d] = "train" if i < n_tr else ("calibration" if i < n_tr + n_ca else "test")
    return out


def stable_hash(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)


def _seconds_of_day(hms: str) -> float:
    h, m, s = (int(x) for x in hms.split(":"))
    return h * 3600 + m * 60 + s


def _ts_rel(ts: str, date: str) -> float:
    dt = datetime.fromisoformat(ts)
    base = datetime.fromisoformat(date)
    return (dt - base).total_seconds()


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def build_bundle(
    route_id: str,
    route: dict[str, Any],
    packages: dict[str, Any],
    matrix: dict[str, dict[str, float]],
    actual: dict[str, Any] | None,
) -> RouteBundle:
    """Validate one route's records and convert them to arrays.

    Missing-value handling: zone ids may be null (kept as None); package
    windows are NaN when absent; stops missing from the travel matrix or with
    non-finite times cause the route to be rejected (reported in ``quality``).
    """
    stops = route.get("stops") or {}
    stations = [s for s, v in stops.items() if v.get("type") == "Station"]
    if len(stations) != 1:
        raise AmazonSchemaError(f"{route_id}: expected exactly one station, found {len(stations)}")
    ids = stations + sorted(s for s in stops if s != stations[0])
    for key in ("station_code", "date_YYYY_MM_DD", "departure_time_utc", "executor_capacity_cm3"):
        if key not in route:
            raise AmazonSchemaError(f"{route_id}: missing {key}")
    missing = [s for s in ids if s not in matrix]
    if missing:
        raise AmazonSchemaError(f"{route_id}: {len(missing)} stops missing from travel matrix")
    n = len(ids)
    tt = np.empty((n, n))
    for i, a in enumerate(ids):
        row = matrix[a]
        try:
            tt[i] = [row[b] for b in ids]
        except KeyError as exc:
            raise AmazonSchemaError(f"{route_id}: incomplete matrix row {a}") from exc
    if not np.all(np.isfinite(tt)) or (tt < 0).any():
        raise AmazonSchemaError(f"{route_id}: non-finite or negative travel times")
    np.fill_diagonal(tt, 0.0)

    lat = np.array([float(stops[s]["lat"]) for s in ids])
    lng = np.array([float(stops[s]["lng"]) for s in ids])
    if not (np.all(np.abs(lat) <= 90) and np.all(np.abs(lng) <= 180)):
        raise AmazonSchemaError(f"{route_id}: coordinates out of range")
    zones = [stops[s].get("zone_id") if isinstance(stops[s].get("zone_id"), str) else None for s in ids]
    date = route["date_YYYY_MM_DD"]
    svc = np.zeros(n)
    vol = np.zeros(n)
    npk = np.zeros(n, dtype=int)
    tws = np.full(n, np.nan)
    twe = np.full(n, np.nan)
    n_bad_pkg = 0
    for i, s in enumerate(ids):
        for p in (packages.get(s) or {}).values():
            st = p.get("planned_service_time_seconds")
            if _finite(st) and st >= 0:
                svc[i] += st
            else:
                n_bad_pkg += 1
            dim = p.get("dimensions") or {}
            d, h, w = dim.get("depth_cm"), dim.get("height_cm"), dim.get("width_cm")
            if all(_finite(x) for x in (d, h, w)):
                vol[i] += d * h * w / 1000.0
            npk[i] += 1
            tw = p.get("time_window") or {}
            a, b = tw.get("start_time_utc"), tw.get("end_time_utc")
            if isinstance(a, str) and isinstance(b, str):
                ra, rb = _ts_rel(a, date), _ts_rel(b, date)
                tws[i] = ra if np.isnan(tws[i]) else max(tws[i], ra)
                twe[i] = rb if np.isnan(twe[i]) else min(twe[i], rb)
    order = list(range(n))
    if actual and isinstance(actual.get("actual"), dict):
        pos = actual["actual"]
        if all(s in pos for s in ids):
            order = sorted(range(n), key=lambda i: pos[ids[i]])
    if order[0] != 0:
        order.remove(0)
        order = [0] + order
    conflicting = int(np.sum(tws > twe))
    tws[tws > twe] = np.nan  # contradictory package windows at one stop: drop
    twe[np.isnan(tws)] = np.nan
    return RouteBundle(
        route_id=route_id,
        station=route["station_code"],
        date=date,
        departure_s=_seconds_of_day(route["departure_time_utc"]),
        capacity_l=float(route["executor_capacity_cm3"]) / 1000.0,
        score=route.get("route_score"),
        stop_ids=ids,
        lat=lat,
        lng=lng,
        zones=zones,
        travel_time=tt,
        service_s=svc,
        volume_l=vol,
        n_packages=npk,
        tw_start_s=tws,
        tw_end_s=twe,
        actual_order=order,
        quality={
            "null_zones": int(sum(z is None for z in zones[1:])),
            "packages_invalid_service": n_bad_pkg,
            "conflicting_windows_dropped": conflicting,
            "stops_with_window": int(np.isfinite(tws).sum()),
        },
    )


# ---------------------------------------------------------------------------
# Persistence of processed bundles
# ---------------------------------------------------------------------------


def save_bundle(b: RouteBundle, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{b.route_id}.json.gz"
    payload = {
        "route_id": b.route_id,
        "station": b.station,
        "date": b.date,
        "departure_s": b.departure_s,
        "capacity_l": b.capacity_l,
        "score": b.score,
        "stop_ids": b.stop_ids,
        "lat": b.lat.round(6).tolist(),
        "lng": b.lng.round(6).tolist(),
        "zones": b.zones,
        "travel_time": b.travel_time.round(1).tolist(),
        "service_s": b.service_s.tolist(),
        "volume_l": b.volume_l.round(3).tolist(),
        "n_packages": b.n_packages.tolist(),
        "tw_start_s": [None if np.isnan(x) else float(x) for x in b.tw_start_s],
        "tw_end_s": [None if np.isnan(x) else float(x) for x in b.tw_end_s],
        "actual_order": b.actual_order,
        "quality": b.quality,
    }
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f)
    return path


def load_bundle(path: Path) -> RouteBundle:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        d = json.load(f)
    nan = float("nan")
    return RouteBundle(
        route_id=d["route_id"],
        station=d["station"],
        date=d["date"],
        departure_s=d["departure_s"],
        capacity_l=d["capacity_l"],
        score=d.get("score"),
        stop_ids=d["stop_ids"],
        lat=np.asarray(d["lat"]),
        lng=np.asarray(d["lng"]),
        zones=d["zones"],
        travel_time=np.asarray(d["travel_time"], dtype=float),
        service_s=np.asarray(d["service_s"], dtype=float),
        volume_l=np.asarray(d["volume_l"], dtype=float),
        n_packages=np.asarray(d["n_packages"], dtype=int),
        tw_start_s=np.asarray([nan if x is None else x for x in d["tw_start_s"]], dtype=float),
        tw_end_s=np.asarray([nan if x is None else x for x in d["tw_end_s"]], dtype=float),
        actual_order=d["actual_order"],
        quality=d.get("quality", {}),
    )


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def haversine_km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = (np.radians(np.asarray(x, dtype=float)) for x in (lat1, lng1, lat2, lng2))
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def expected_schedule(b: RouteBundle) -> np.ndarray:
    """Expected arrival (s after 00:00 UTC) at each stop along the observed
    driver sequence, using observed average travel and planned service times."""
    eta = np.zeros(len(b.stop_ids))
    t = b.departure_s
    prev = 0
    for i in b.actual_order[1:]:
        t += b.travel_time[prev, i]
        eta[i] = t
        t += b.service_s[i]
        prev = i
    eta[0] = b.departure_s
    return eta


# ---------------------------------------------------------------------------
# Merged multi-vehicle instances
# ---------------------------------------------------------------------------


@dataclass
class MergeConfig:
    promise_window_s: float = 7200.0  # synthetic promise window width
    window_grid_s: float = 1800.0  # promise windows start on a 30-minute grid
    shift_slack: float = 1.25  # shift end = latest (departure + slack * expected duration)
    reserve_vehicles: int = 1
    vehicle_fixed_cost_s: float = 3600.0  # dispatch cost: 1 h of driving-time equivalent


def merge_routes(
    bundles: list[RouteBundle],
    estimator=None,
    cfg: MergeConfig | None = None,
    instance_id: str | None = None,
) -> Instance:
    """Combine same-station, same-day routes into one multi-vehicle instance.

    * Within-route travel times are the observed averages from the dataset.
    * Cross-route stop pairs were never observed together; their expected
      travel time (and estimation uncertainty) comes from ``estimator`` — the
      calibrated travel-time model. Without an estimator, a haversine speed
      fit on the instance's own observed arcs is used and flagged.
    * Every stop gets a promise window: the real package window if one exists
      (observed), otherwise a synthetic window anchored on the stop's expected
      arrival along the historically observed driver sequence.
    """
    cfg = cfg or MergeConfig()
    if not bundles:
        raise ValueError("no routes to merge")
    if len({(b.station, b.date) for b in bundles}) != 1:
        raise ValueError("routes must share station and date")
    b0 = bundles[0]
    t0 = min(b.departure_s for b in bundles)
    # node layout: depot, then each route's dropoffs
    owner: list[int] = [-1]
    local: list[int] = [0]
    for r, b in enumerate(bundles):
        for i in range(1, len(b.stop_ids)):
            owner.append(r)
            local.append(i)
    n = len(owner)
    lat = np.empty(n)
    lng = np.empty(n)
    lat[0], lng[0] = b0.lat[0], b0.lng[0]
    for k in range(1, n):
        b = bundles[owner[k]]
        lat[k], lng[k] = b.lat[local[k]], b.lng[local[k]]

    tt = np.full((n, n), np.nan)
    observed = np.zeros((n, n), dtype=bool)
    for r, b in enumerate(bundles):
        idx = [0] + [k for k in range(1, n) if owner[k] == r]
        loc = [local[k] for k in idx]
        sub = b.travel_time[np.ix_(loc, loc)]
        ii = np.ix_(idx, idx)
        # depot rows/cols are observed in every route; average them
        prev = tt[ii]
        tt[ii] = np.where(np.isnan(prev), sub, (prev + sub) / 2.0)
        observed[ii] = True
    rel_sd = np.zeros((n, n))
    missing = ~observed
    est_source = "none"
    if missing.any():
        zones = [None] + [bundles[owner[k]].zones[local[k]] for k in range(1, n)]
        if estimator is not None:
            pred, sd = estimator.predict_pairs(lat, lng, zones, b0.station, t0, missing)
            est_source = "travel-time model (LightGBM quantile + conformal)"
        else:
            pred, sd = _speed_fit_estimate(lat, lng, tt, observed, missing)
            est_source = "haversine speed fit (fallback)"
        tt[missing] = pred
        rel_sd[missing] = sd
    np.fill_diagonal(tt, 0.0)
    np.fill_diagonal(observed, True)

    service = np.zeros(n)
    volume = np.zeros(n)
    tw_e = np.zeros(n)
    tw_l = np.zeros(n)
    tw_src: list[str] = ["depot"]
    stop_ids = ["depot"]
    zones_out: list[str | None] = [None]
    shift_end = 0.0
    for r, b in enumerate(bundles):
        eta = expected_schedule(b)
        dur = eta[b.actual_order[-1]] + b.service_s[b.actual_order[-1]] + b.travel_time[b.actual_order[-1], 0] - b.departure_s
        shift_end = max(shift_end, b.departure_s - t0 + cfg.shift_slack * dur)
    for k in range(1, n):
        b = bundles[owner[k]]
        i = local[k]
        service[k] = b.service_s[i]
        volume[k] = b.volume_l[i]
        stop_ids.append(f"R{owner[k] + 1}-{b.stop_ids[i]}")
        zones_out.append(b.zones[i])
        if np.isfinite(b.tw_start_s[i]):
            tw_e[k] = b.tw_start_s[i] - t0
            tw_l[k] = b.tw_end_s[i] - t0
            tw_src.append("observed")
        else:
            eta = expected_schedule(b)[i] - t0
            start = math.floor((eta - cfg.promise_window_s / 2) / cfg.window_grid_s) * cfg.window_grid_s
            tw_e[k] = max(0.0, start)
            tw_l[k] = start + cfg.promise_window_s
            tw_src.append("synthetic")
    tw_e = np.clip(tw_e, 0.0, shift_end)
    tw_l = np.clip(tw_l, 0.0, shift_end)
    tw_e = np.minimum(tw_e, tw_l)
    tw_l[0] = shift_end
    capacity = min(b.capacity_l for b in bundles)
    volume = np.minimum(volume, capacity)
    city = b0.city
    offset = CITY_UTC_OFFSET_H.get(city, 0)
    n_obs_tw = sum(1 for s in tw_src if s == "observed")
    iid = instance_id or f"amazon/{b0.station}-{b0.date}-{'-'.join(b.route_id[8:14] for b in bundles)}"
    return Instance(
        id=iid,
        name=f"{CITY_NAME.get(city, city)} {b0.station} · {b0.date} · {len(bundles)} routes",
        source="amazon",
        coord_system="wgs84",
        coords=np.column_stack([lng, lat]),
        travel_time=tt,
        distance=tt.copy(),  # objective: expected driving time (no road distances in the data)
        service=service,
        tw_early=tw_e,
        tw_late=tw_l,
        demand=volume,
        capacity=capacity,
        num_vehicles=len(bundles) + cfg.reserve_vehicles,
        time_unit="s",
        distance_unit="s",
        int_scale=1.0,
        vehicle_fixed_cost=cfg.vehicle_fixed_cost_s,
        has_tw=np.array([False] + [True] * (n - 1)),
        tt_observed=observed,
        tt_rel_sd=rel_sd,
        stop_ids=stop_ids,
        zones=zones_out,
        provenance={
            "dataset": "Amazon Last Mile Routing Research Challenge 2021 (training split)",
            "license": LICENSE,
            "citation": CITATION,
            "observed": [
                "stop coordinates (WGS84)",
                "within-route average travel times",
                "planned service times",
                "package volumes and vehicle capacity",
                f"package time windows ({n_obs_tw} stops)",
                "driver stop sequences (used to anchor promise windows)",
            ],
            "model_estimated": [f"cross-route travel times ({est_source})"],
            "synthetic": [
                f"promise windows for {n - 1 - n_obs_tw} stops ({cfg.promise_window_s / 3600:.0f}-hour windows anchored on "
                "expected arrival along the observed driver sequence)",
                f"shift end ({cfg.shift_slack:.2f} x expected observed-route duration)",
                f"{cfg.reserve_vehicles} reserve vehicle(s); dispatch cost = {cfg.vehicle_fixed_cost_s / 3600:.0f} h of driving per vehicle used",
                "stochastic travel/service variability (KAIROS scenario model)",
                "disruptions",
            ],
            "objective_note": "Travel cost is expected driving time in seconds; the dataset has no road distances.",
            "map_note": "Stops are plotted at published coordinates; route lines are straight segments between "
            "consecutive stops, not road geometry.",
        },
        meta={
            "station": b0.station,
            "date": b0.date,
            "city": CITY_NAME.get(city, city),
            "utc_offset_h": offset,
            "t0_utc_s": t0,
            "route_ids": [b.route_id for b in bundles],
            "route_owner": owner,
            "tw_source": tw_src,
            "share_tt_observed": float(observed.mean()),
            "n_observed_windows": n_obs_tw,
            "estimation_source": est_source,
        },
    )


def _speed_fit_estimate(lat, lng, tt, observed, missing):
    """Fallback: log-log fit of observed travel time on haversine distance."""
    d = haversine_km(lat[:, None], lng[:, None], lat[None, :], lng[None, :])
    m = observed & (d > 0.01) & (tt > 0)
    x, y = np.log(d[m]), np.log(tt[m])
    a, c = np.polyfit(x, y, 1)
    resid = y - (a * x + c)
    sd = float(resid.std())
    pred = np.exp(a * np.log(np.maximum(d[missing], 0.01)) + c + sd**2 / 2)
    return pred, np.full(pred.shape, sd)


def iter_processed_bundles(directory: Path = AMAZON_PROCESSED_DIR / "routes") -> Iterator[RouteBundle]:
    for p in sorted(directory.glob("*.json.gz")):
        yield load_bundle(p)
