# KAIROS build log

Concise record of decisions, state and open items (kept current so work can resume).

## Decisions
- **Competition**: DataNova 2026 problem statements were not yet published on datanovathon.com on 2026-10-29
  (release deadline 30 Oct 2026); DN-OR-01 wording could not be verified. Final submission 25 Nov 2026.
- **Python 3.11 venv** (system default 3.14 untested); PyVRP 0.14.1, LightGBM 4.7.
- **Amazon data has no realised trip/service durations** -> variability is a documented synthetic model; the
  real-data ML task is travel-time estimation (LightGBM quantiles + CQR) for never-observed stop pairs.
- **Split by date** (27/6/6 dates). Test dates contain only DLA9, DSE2, DSE4, DSE5.
- **Amazon instances**: 2 same-day routes + 1 reserve van, 1 h dispatch cost per vehicle, synthetic 2 h promise
  windows anchored on the observed driver sequence (real windows kept where present).
- **Solver**: iteration-budget stopping (deterministic per seed), default 5000; reliability planner gives 40% to
  beta=0 and warm-starts the ladder; conservative integer rounding (durations ceil, latest times floor).
- **Basemap**: CARTO now needs an API key -> OpenStreetMap tiles in greyscale.

## State (2026-10-29)
- All components working; 45 backend + 10 frontend tests pass; production build OK; backend serves the built UI.
- Final experiments complete, 0 failed runs (artifacts/experiments/*.json); docs/RESULTS.md generated.
- Presentation: Slides artifact https://claude.ai/artifact/W7aG2ZMTf6JVZkZ5UKPyjk (sources in docs/presentation/).

## Open items
- Verify against the official DN-OR-01 statement once published.
- Not deployed publicly; Dockerfile not build-tested (Docker unavailable here).
- Possible improvements: warm-start Amazon solves from historical driver routes; penalise plan churn in replanning;
  calibrate the variability model on real telematics.
