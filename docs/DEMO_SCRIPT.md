# Demo script (about 6 minutes, video-ready)

Setup: backend and frontend running (see README), browser at http://localhost:5173 (or :8000 with the
built UI), window at least 1280 px wide. Every number you will see is computed live or read from stored
experiment artifacts; none is typed into the UI.

## 0. Framing (30 s)
"A route that is optimal on paper fails when travel or service times move. KAIROS asks whether planning
for that uncertainty — and replanning when something goes wrong — reduces late deliveries, and what it costs."

## 1. The data (45 s) — Route Studio
1. Dataset **Amazon**, instance **DLA9 · 2018-08-24** (Long Beach, 221 stops, two historical routes plus a reserve van).
2. Point to the tags: *Observed benchmark*, *49% arcs model-estimated*, *Synthetic variability*.
   Hover a stop: window marked *(synthetic)* or *(observed)*, planned service time.
3. Say: "The map uses real coordinates; lines will be straight segments, not roads — the dataset has no road geometry."

## 2. Baseline vs KAIROS (90 s)
1. For a clear effect, switch to **Solomon → RC105** (tight windows). Keep target **95%**, uncertainty **Medium**,
   budget **Standard**. Click **Run comparison**; note the live progress ("Candidate 3/5, buffer 1.00").
2. Decision panel: baseline on-time vs KAIROS on-time, the paired delta with its 95% CI, travel cost delta,
   vehicles, compute time. Verdict pill: *Target met out-of-sample*.
3. **Why this plan**: the frontier chart — five buffered candidates, the target line, the chosen (cheapest
   qualifying) candidate, and the baseline / chosen plan measured out-of-sample.
4. Toggle **Plan shown: Baseline ↔ KAIROS** — stops recolour by simulated risk. The schedule strip shows windows
   against simulated P10–P90 arrival bands; click a row to isolate a vehicle.

## 3. The target is a real control (30 s)
Drag the target to **99%**, run again: a larger buffer is chosen, cost rises, on-time rises (or the panel says the
target could not be met in-sample). Drag to **85%**: the cheaper plan returns.

## 4. Disruption (90 s) — Disruption Lab
1. Plan in operation: **Baseline**. Event: **Vehicle breakdown**, vehicle 1, at about 30% of the day.
   Click **Inject and replan**.
2. Outcome table: Hold + insert vs Re-optimise vs KAIROS replan — on-time, lateness, cost, stops reassigned,
   replan time. Map: completed stops grey, reassigned stops ringed, spare vehicles dashed.
3. "What changed": the broken vehicle, stops moved (from → to), the safety buffer selected.
4. Optional: **Urgent order** on an Amazon instance — click the map to place it; its travel times come from the
   calibrated travel-time model.

## 5. Evidence (60 s)
1. Headline cards: Solomon on-time gain with CI and cost; target attainment; Amazon at 95% and 99% targets;
   disruptions.
2. Forest plots: buffer-only vs selection-only vs KAIROS — the combination is the cost-efficient one; gains
   concentrate on tight-window classes; none on wide-window classes (and none at the lenient Amazon 95% target).
3. Misspecification: if the planner underestimates variability, the target is missed — the honest limitation.
4. Travel-time model: conformal coverage on future dates sits on the diagonal.

## 6. Close (15 s)
"Reproducible from four commands; every number regenerates from the artifacts. What it does not show: real
operational variability — the next step is calibrating the scenario model on telematics data."
