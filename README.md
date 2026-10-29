# KAIROS — reliability-aware last-mile routing under uncertainty

KAIROS plans delivery routes that are meant to stay on time when travel and service times move, re-plans
when something goes wrong, and measures — honestly — what that reliability costs. Built for the
**DataNova 2026 Global Data-thon** (Optimization & Decision Intelligence).

> **Research question.** Can uncertainty-aware, dynamically re-optimised delivery routes reduce
> delivery-window violations under controlled operational disruptions, compared with a deterministic routing
> baseline, while maintaining acceptable route efficiency and computational performance?

**Competition note.** On 2026-10-29 the DataNova site listed 30 Oct 2026 as the problem-statement release
deadline; the DN-OR-01 statement was not yet published, so its exact wording and requirements could **not**
be verified. KAIROS targets the stated judging criteria and a defensible last-mile routing problem; re-check
the official statement before submission (final submission: 25 Nov 2026).

---

## What it does

| Component | Implementation |
|---|---|
| Data | Amazon Last Mile Routing Research Challenge (6,112 routes, validated, chronologically split) and 56 Solomon VRPTW instances; synthetic fallback |
| Prediction with calibrated uncertainty | LightGBM quantile regression + conformalized quantile regression for stop-to-stop travel times, validated on **later dates** (real outcome data) |
| Scenario model | Seeded, documented stochastic model of travel/service variability (synthetic — the data contain no realised trip times) |
| Optimisation | PyVRP 0.14 VRPTW (time windows, capacities, multiple depots, dispatch cost) |
| Reliability-aware planning | Ladder of buffered plans + chance-constrained selection on in-sample scenarios; the target is the constraint's right-hand side |
| Dynamic replanning | Fleet state at the event time → residual VRP with pseudo-depots → hold-and-insert / re-optimise / reliability replan |
| Evaluation | Out-of-sample Monte Carlo with common random numbers, paired bootstrap CIs, Wilcoxon tests, ablations, sensitivity |
| Product | FastAPI + React/TypeScript "Route Studio": live map, schedule bands, decision panel, Disruption Lab, Evidence, Data & Method |

## Results (measured; full tables in [docs/RESULTS.md](docs/RESULTS.md))

All numbers come from `artifacts/experiments/*.json`. Variability and disruptions are **synthetic**; plans
are PyVRP outputs; metrics are simulated on scenarios the planners never saw. Target = 95% unless stated.

| Experiment | Baseline | KAIROS | Effect (95% CI) | Cost |
|---|---:|---:|---|---:|
| Solomon, 56 instances — on-time stops | 91.8% | 98.3% | **+6.5 pt** [4.8, 8.4], p < 0.001 | +13.1% distance |
| Solomon — instances meeting the 95% target out-of-sample | 39% | **100%** | | |
| Solomon short-horizon classes C1 / R1 / RC1 | | | +13.2 / +7.5 / +6.8 pt | +36 / +10 / +13% |
| Solomon C2 (long horizon, long service times) | | | +12.0 pt | +21% |
| Solomon R2 / RC2 (long horizon, wide windows) | | | +0.1 / +0.2 pt (≈ 0; little buffer chosen) | +0.4 / +0.5% |
| Amazon, 24 station-days, target 95% | 97.95% | 97.94% | no effect (baseline already meets target) | +0.3% |
| Amazon, target 99% | 97.95% | **99.70%** | **+1.74 pt** [1.30, 2.18]; target met 88% vs 12.5% | +12.5% driving time |
| Disruptions, Solomon (1,080 policy runs) — residual on-time | 76.7% (baseline plan + hold) | 97.1% (KAIROS plan + KAIROS replan) | +20.4 pt [17.8, 23.1] | +6.8% residual cost |
| Disruptions, Amazon (1,080 policy runs) — residual on-time | 79.9% (baseline plan + hold) | 95.5% (KAIROS plan + KAIROS replan) | +15.7 pt [12.5, 19.1]; plain re-optimise: +14.8 pt | +10.8% residual cost |
| Travel-time model, test dates — MAE | 61.9 s (speed fit) | 54.3 s | −12% | |
| Travel-time model — 90% interval coverage | 89.2% (speed fit) | **90.2%** (conformal) | intervals 25% narrower | |

What the ablations show: safety buffers alone are reliable but expensive (+8.0 pt at +31% distance) and
backfire at very high targets (Amazon 99%: −8.2 pt, because over-buffered windows become infeasible);
scenario selection alone is cheap but weak (+0.7 pt). The combination — a buffer ladder plus
chance-constrained selection — is what reaches the target at the lowest cost. In the dynamic experiments on
Solomon, most of the gain comes from the reliability-aware **initial** plan (KAIROS plan + simple hold: 94.9%);
reliability replanning adds a further +2.2 pt; deterministic re-optimisation of a deterministic plan reaches
88.6%. On Amazon the picture differs: re-planning *itself* recovers the loss (re-optimise 94.7%, KAIROS replan
95.1%), reliability-aware replanning adds only +0.4 pt at 2.8× the replan time (4.1 s vs 1.5 s), and the
static KAIROS plan alone brings nothing (its 95% target is already met by the baseline).

**Limitations that bound these claims:** the reliability gains are measured under a synthetic variability
model; if the planner underestimates variability by half, the 95% target is met on only 58% of
instances (overestimating it by 1.5× gives 83%; Experiment 3); on-time rates are expected shares, not route-level guarantees; Amazon test dates
cover two cities. See [Limitations](#limitations).

---

## Quick start (Windows)

Prerequisites: Python 3.11 (3.10–3.13 work; 3.14 is not tested), Node.js 20+.

```powershell
.\scripts\setup.ps1            # venv, Python deps, npm install, frontend build
.\scripts\run_backend.ps1      # API (and built UI) on http://127.0.0.1:8000
.\scripts\run_frontend.ps1     # optional: dev UI with hot reload on http://localhost:5173
```

Open http://127.0.0.1:8000. The app works immediately with the shipped data: 56 Solomon instances, three
Amazon demo instances (`data/demo/amazon`), the trained travel-time model and the stored experiment results.

Manual setup (any OS):

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt        # Windows: .venv\Scripts\pip
cd frontend && npm install && npm run build && cd ..
.venv/bin/python -m uvicorn kairos.api.app:app --port 8000
```

## Reproducing the research pipeline

```bash
bash scripts/download_amazon.sh                 # ~2.3 GB public S3 download, no AWS account
python scripts/prepare_amazon.py                # validate, profile, split by date (~2.5 min)
python scripts/train_traveltime.py              # quantile models + conformal calibration (~3 min)
python scripts/build_amazon_instances.py        # 24 merged instances from test dates
python scripts/run_experiments.py --suite all --workers 8   # all experiments (~25 min on 20 cores)
python scripts/build_report.py                  # regenerate docs/RESULTS.md
```

`--quick` gives a smoke-scale run in about a minute. Each suite can be run alone
(`--suite static_solomon`, `dynamic_amazon`, …). Seeds and budgets are recorded in every artifact.

## Tests

```bash
.venv/Scripts/python -m pytest          # 45 backend tests
cd frontend && npm test                 # 10 frontend tests (vitest + Testing Library)
cd frontend && npm run build            # type-check + production build
```

Backend tests cover data validation and preprocessing (Solomon, Amazon bundles, chronological split,
merging), solver feasibility and reproducibility, the reliability target's effect, simulation arithmetic and
common random numbers, every disruption type and replanning policy, statistics, conformal calibration, and
API success and error paths. Frontend tests cover formatting, charts and the core workflow against a mocked
backend (the target control changes the request; results render from the response; offline state).

## Architecture

```
kairos/
  config.py                 portable paths and defaults (env overrides)
  data/        schema.py    Instance dataclass + validation
               solomon.py   Solomon parser
               amazon.py    Amazon validation, bundles, chronological split, merged instances
               synthetic.py seeded fallback instances
               registry.py  instance catalogue and serialisation
  uncertainty/ stochastic.py   scenario model (common random numbers)
               traveltime.py   LightGBM quantiles + CQR
  solver/      vrp.py       typed PyVRP adapter (ProblemData from numpy, multi-depot residual problems)
               planners.py  deterministic / buffered / selection / reliability planners
  sim/         montecarlo.py   vectorised plan execution and metrics
               dynamic.py      state observation, events, residual problems, replanning policies, diffs
  eval/        stats.py, experiments.py   paired statistics and experiment suites
  service.py                orchestration + JSON shaping (HTTP-free, testable)
  api/         app.py, jobs.py   FastAPI with background jobs and progress polling
frontend/src/
  api/          typed client + job polling
  state/        app store (selected instance, planner settings, comparison run)
  components/   design-system primitives, map (Leaflet / benchmark-space SVG), charts
  views/        Route Studio, Disruption Lab, Evidence, Data & Method
scripts/        download, prepare, train, build instances, experiments, report
artifacts/      models/traveltime, experiments/*.json, data_profile
docs/           METHOD, DATA, RESULTS (generated), DEMO_SCRIPT, DEPLOYMENT, PROGRESS
```

API (all expensive calls are background jobs polled at `GET /api/jobs/{id}`):

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | status, solver and model availability |
| `GET /api/datasets`, `GET /api/datasets/amazon/profile` | catalogue and ingestion profile |
| `GET /api/instances[?source=]`, `GET /api/instances/{id}` | instance list / detail with provenance |
| `POST /api/plans`, `POST /api/compare` | plan one method / compare methods (paired evaluation) |
| `GET /api/plans/{plan_id}` | stored plan |
| `POST /api/disruptions` | inject an event into a plan and replan under chosen policies |
| `GET /api/experiments[/{name}]`, `GET /api/models/travel-time` | stored evidence |

## Data provenance

See [docs/DATA.md](docs/DATA.md). In short: Amazon coordinates, within-route travel times, service times,
volumes, capacities, real package windows (6.5% of stops) and driver sequences are **observed**; cross-route
travel times are **model-estimated**; promise windows for the other stops, shift end, reserve van, dispatch
cost, all variability and all disruptions are **synthetic**. Amazon data © Amazon, CC BY-NC 4.0 — cite
Merchán et al. (2022). Solomon (1987). Map tiles © OpenStreetMap contributors.

## Limitations

* No dataset used contains realised trip or service durations: reliability is evaluated under a documented
  synthetic variability model, not observed operations. Real-world calibration would need telematics with
  per-stop arrival/departure timestamps (the travel-time pipeline would carry over unchanged).
* Results depend on the planner's uncertainty model being right; underestimating dispersion degrades target
  attainment sharply (Experiment 3).
* The on-time rate is an expected share of stops, estimated per scenario; it is not a route-level guarantee,
  and marginal coverage of the travel-time intervals does not transfer to routes.
* Amazon instances: test dates cover four stations in two cities; the objective is expected driving time (no
  road distances); map lines are straight segments; synthetic promise windows are lenient, so effects appear
  only at high targets.
* Disruptions are known to the planner once they occur; broken-down vehicles' packages are assumed
  transferable; disruption parameters are illustrative.
* PyVRP is a heuristic: with a fixed iteration budget it occasionally ends in a local optimum that uses the
  reserve van on Amazon instances; all planners face the same budget, and vehicles used are reported.
* Full re-optimisation after a disruption can reassign many stops (over 100 on a 236-stop instance for a
  single urgent order); plan stability is reported (stops reassigned) but not penalised in the objective.
* Runtimes in experiments were measured with 10 parallel workers on one machine.
* Not deployed publicly from this environment; the Dockerfile has not been build-tested (Docker unavailable).
  See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Troubleshooting

* **"Backend offline" banner** — start `scripts/run_backend.ps1`; the dev UI proxies `/api` to port 8000
  (override with `KAIROS_API`).
* **Python 3.14** — create the venv with Python 3.11 (`py -3.11 -m venv .venv`).
* **No Amazon instances listed** — the three demo instances live in `data/demo/amazon`; the full set is built
  by the pipeline above. The UI falls back to Solomon if none exist.
* **Blank map tiles** — tiles load from tile.openstreetmap.org; offline, stops and routes still render.
* **Slow first instance list** — Amazon instance files are parsed once and cached.

## Licence

No licence has been chosen for the code yet (add one before publishing). Amazon-derived data: CC BY-NC 4.0 (non-commercial).
