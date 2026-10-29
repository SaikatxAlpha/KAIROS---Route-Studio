# Data, provenance and licences

## Sources

| Dataset | Use in KAIROS | Licence / citation |
|---|---|---|
| **Amazon Last Mile Routing Research Challenge (2021)**, training inputs: `route_data.json`, `package_data.json`, `travel_times.json`, `actual_sequences.json` (6,112 routes, 2018, five US metros) | Real geography, observed average travel times, planned service times, package windows, capacities, driver sequences; travel-time model training/validation; merged instances | CC BY-NC 4.0. Merchán, D., Arora, J., Pachon, J., Konduri, K., Winkenbach, M., Parks, S., Noszek, J. (2022). *2021 Amazon Last Mile Routing Research Challenge: Data Set.* Transportation Science. Accessed 2026-10-29 from https://registry.opendata.aws/amazon-last-mile-challenges |
| **Solomon VRPTW benchmark** (56 instances, 100 customers) | Multi-vehicle time-window benchmark | Solomon, M. M. (1987). Operations Research 35(2):254–265. Public benchmark files (shipped in `data/benchmarks/solomon`). |
| **OpenStreetMap** tiles | Basemap in the UI (greyscale) | © OpenStreetMap contributors, ODbL; light interactive use per the OSM tile policy. |

The evaluation split of the Amazon challenge (3,072 routes) was not used; all experiments use the training
inputs with KAIROS's own chronological split.

## What the Amazon data contain — and do not contain

Verified against the official data-structure documentation and the files:

* contained: stop lat/lng (WGS84), stop type, zone id (6,515 nulls), station, date, departure time (UTC),
  vehicle capacity (cm³), route quality score; per-package planned service time, dimensions, scan status and
  time window (present for 6.5% of stops, median width 8 h); per-route stop-to-stop matrix of *average*
  historically realised travel times; the stop order the driver actually followed.
* **not** contained: realised per-trip travel or service times, arrival timestamps, live traffic, breakdowns,
  road distances or road geometry.

## Pipeline (`scripts/prepare_amazon.py`)

* Streams the 1.8 GB matrix file (ijson) — no full in-memory load.
* Validation per route (`kairos/data/amazon.py::build_bundle`): exactly one station; required fields;
  complete, finite, non-negative matrix; coordinate ranges. Rejected routes are counted in
  `profile.json` (result: 0 of 6,112 rejected).
* Missing values: null zone ids kept as missing; packages without a window → NaN; packages with NaN
  dimensions are excluded from volume; contradictory package windows at one stop would be dropped (none found).
* **Chronological split by date**: train 2018-07-19…08-14 (27 dates, 4,881 routes), calibration
  08-15…08-20 (6 dates, 872 routes), test 08-21…08-26 (6 dates, 359 routes). Splitting by date prevents
  same-day leakage between arcs of different routes. The test dates contain only stations DLA9 (Los Angeles)
  and DSE2/DSE4/DSE5 (Seattle).
* 400 random arcs per route are sampled for the travel-time model (1.95 M train, 0.35 M calibration,
  0.14 M test arcs; training uses a 1.2 M subsample).

Profile: `artifacts/data_profile/amazon_profile.json` (shipped).

## Merged Amazon instances (`scripts/build_amazon_instances.py`)

For each test-date station-day: a deterministically chosen route plus its nearest same-day route (by stop
centroid) are merged into one multi-vehicle instance (172–316 stops, 24 instances).

| Element | Provenance |
|---|---|
| Stop coordinates, within-route travel times, planned service times, volumes, capacity | observed |
| Real package windows (3–51 stops per instance) | observed |
| Cross-route travel times (≈ 50% of arcs) | **model-estimated** (travel-time model, never trained on test dates) |
| 2-hour promise windows for the remaining stops, anchored on each stop's expected arrival along the observed driver sequence, starting on a 30-minute grid | **synthetic** |
| Shift end = latest (departure + 1.25 × expected observed-route duration) | **synthetic assumption** |
| One reserve van; dispatch cost of 1 h driving per vehicle used | **synthetic assumption** |

Three of these instances are shipped in `data/demo/amazon/` so the app works without downloading the
dataset (redistribution under CC BY-NC 4.0 with attribution, non-commercial).

## Synthetic data

* `synthetic/demo-*` instances (`kairos/data/synthetic.py`) — seeded generator, used as an offline
  fallback and in tests; never mixed into benchmark results.
* Scenario variability and all disruptions — see [METHOD.md](METHOD.md).

## Labelling in the product

Every screen tags what it shows: *Observed data*, *Model estimate*, *Synthetic*, *Algorithm output* (PyVRP
plans) and *Measured* (simulation outcomes). Map lines on Amazon instances are straight segments between
consecutive stops, captioned as such.
