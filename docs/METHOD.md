# Method

## Research question

> Can uncertainty-aware, dynamically re-optimised delivery routes reduce delivery-window violations under
> controlled operational disruptions, compared with a deterministic routing baseline, while maintaining
> acceptable route efficiency and computational performance?

Treated as a hypothesis. Results (including null and negative ones) are in [RESULTS.md](RESULTS.md).

## 1. Problem

Vehicle routing with time windows (VRPTW): a fleet based at one depot serves every stop once; each stop has a
service duration and a window `[e_i, l_i]` in which service must *start*; vehicles have a capacity and a
shift (depot window). The routing objective is travel cost (Euclidean distance for Solomon; expected driving
time for Amazon, which has no road distances) plus, on Amazon instances, a dispatch cost of one hour of
driving per vehicle used (an assumption applied identically to every planner).

In execution, travel and service times are random. A stop is **late** when the vehicle arrives after `l_i`
(it is still served; lateness is measured, not prevented). The headline reliability metric is the
**on-time rate**: the share of windowed stops reached by `l_i`, averaged over scenarios. Also reported:
probability that *all* windows are met, total lateness, overtime probability, cost, vehicles, runtime.

## 2. Uncertainty model (synthetic, explicit)

Neither benchmark records realised per-trip durations, so variability cannot be calibrated from outcomes.
KAIROS uses a transparent multiplicative model (`kairos/uncertainty/stochastic.py`):

```
travel(i,j | scenario s, vehicle k) = t_ij · D_s · V_sk · E_sij · B_sij
service(i | s)                      = s_i  · G_si
```

| Factor | Meaning | Distribution | `medium` default |
|---|---|---|---|
| `D_s` | day-level congestion, shared by all arcs (creates correlation) | lognormal, mean 1 | σ = 0.08 |
| `V_sk` | vehicle / driver pace | lognormal, mean 1 | σ = 0.05 |
| `E_sij` | idiosyncratic traversal noise | lognormal, mean 1 | σ = 0.25 |
| `B_sij` | estimation error on arcs whose time was *model-estimated* | lognormal, mean 1 | σ from the calibrated travel-time model |
| `G_si` | service-time variability | gamma, mean 1 | CV = 0.40 |

`low` and `high` presets scale these (see `UncertaintyConfig.preset`). Because every factor has unit mean,
`t_ij` stays the expectation and the deterministic baseline plans on unbiased inputs.

Scenario `s` depends only on `(seed, s)`, with separate random streams per component, so every planner is
evaluated on identical realisations (**common random numbers**). Planner (in-sample) and evaluation
(out-of-sample) streams use disjoint seed offsets (`kairos/config.py`).

## 3. Planners (`kairos/solver/planners.py`)

All planners call PyVRP 0.14.1 (hybrid genetic search with hard time windows, capacities, multiple depots
and vehicle types) through `kairos/solver/vrp.py`. Search stops after a fixed **iteration budget**
(deterministic for a seed) with a wall-clock safety cap; all planners in a comparison get the **same total
budget** (default 5000 iterations).

| Planner | What it does | Role |
|---|---|---|
| Deterministic | VRPTW on expected travel and service times | baseline |
| Quantile buffer | VRPTW on `mean + z_α·sd` durations (α = target), one solve | ablation: buffering only |
| Scenario selection | 5 deterministic solves (different seeds), pick the one with the best in-sample on-time rate subject to the target, else cheapest | ablation: selection only |
| **KAIROS reliability** | ladder of buffered VRPTW solves, β ∈ {0, 0.5, 1, 1.5, 2} standard deviations, warm-started along the ladder; each candidate simulated on in-sample scenarios; choose the **cheapest candidate whose estimated on-time rate ≥ target** (sample-average approximation of a chance constraint); if none qualifies, the most reliable candidate is returned and flagged | proposed |

The β = 0 candidate receives 40% of the budget and the remaining candidates share the rest (they are
warm-started). The **reliability target** has a direct mathematical effect: it is the right-hand side of the
chance constraint used to select the plan.

Integer conversion for PyVRP is conservative (durations rounded up, latest service times rounded down), so a
plan feasible in the solver is feasible in the continuous-time simulator.

**What the target is not.** It is an estimate of the expected share of stops served on time under the
assumed uncertainty model, validated out-of-sample under that model. It is not a route-level guarantee, and
it is only as good as the uncertainty model (see the misspecification experiment).

## 4. Evaluation (`kairos/sim/montecarlo.py`)

Vectorised execution of each route over scenario blocks: arrive, wait if early, record lateness if after
`l_i`, serve, continue; overtime if returning after the depot closes. Per-stop arrival quantiles (P10/P50/P90)
and lateness probabilities feed the UI.

## 5. Dynamic replanning (`kairos/sim/dynamic.py`)

1. **State.** The plan executes in one realised world up to the event time τ. Completed stops are fixed; each
   vehicle is committed to the stop it is driving to or serving; it becomes available there at its *expected*
   completion time given observed progress.
2. **Event** (synthetic, user-configured): traffic (travel × f on arcs touching an area), weather (all travel
   × f, service × (1 + (f − 1)/2)), service shock (service × f in an area), breakdown (vehicle removed; its
   committed and remaining stops orphaned; packages assumed transferable), urgent order (new stop with a tight
   window; Amazon travel times to it come from the travel-time model).
3. **Residual problem.** Each active vehicle becomes its own PyVRP vehicle type with a pseudo-depot at its
   committed stop and an earliest start at its availability time; unused vehicles start at the depot at τ with
   the dispatch cost.
4. **Policies.** *Hold + insert* (keep sequences, cheapest insertion of orphaned/new stops — local repair),
   *Re-optimise* (PyVRP on expected disrupted times, warm-started from hold), *KAIROS replan* (the reliability
   ladder and chance-constrained selection on the residual problem).
5. **Evaluation** of every policy on the same out-of-sample scenarios of the residual horizon, plus a diff
   (stops reassigned, vehicles resequenced).

## 6. Travel-time estimation with calibrated uncertainty (`kairos/uncertainty/traveltime.py`)

The one place where real outcome data exist: Amazon's matrices of *average historically realised* travel
times. A LightGBM model predicts log travel time between two stops from geometry and context (haversine
distance, displacement, bearing, zone relationships, station, departure hour, position relative to the
station), one model per quantile (0.025 … 0.975) with monotone rearrangement. **Conformalized quantile
regression** (Romano et al., 2019) widens each central interval by the finite-sample quantile of conformity
scores on a held-out *calibration* date block; coverage is measured on a later *test* date block.

Uses: expected travel time and estimation sd for stop pairs never observed together (cross-route pairs in
merged instances, urgent orders). The estimation sd enters the scenario model as `B_sij`.

## 7. Experimental design

* Instances: 56 Solomon (all); 24 Amazon merged station-days from held-out test dates.
* Paired comparisons per instance under common random numbers; summaries are means with percentile
  bootstrap 95% CIs across instances and two-sided Wilcoxon signed-rank tests.
* Ablations: buffer-only, selection-only, combined; dynamic factorial of base plan × replanning policy.
* Sensitivity: target sweep, variability level, planner misspecification (planner assumes dispersion ×0.5 …
  ×1.5 of the truth).
* Failures are recorded in the artifacts (`n_failed`, `failures`), never dropped.
* Reproduce: `python scripts/run_experiments.py --suite all`.
