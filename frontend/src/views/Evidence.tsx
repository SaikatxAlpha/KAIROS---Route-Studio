import { useEffect, useMemo, useState } from "react";
import { FlaskConical, Terminal } from "lucide-react";
import { api } from "../api/client";
import type { Method } from "../api/types";
import { ForestPlot, type ForestRow } from "../components/charts/ForestPlot";
import { LineChart } from "../components/charts/LineChart";
import { Empty, ErrorNote, Legend, Progress, ProvTag, StatusPill } from "../components/ui";
import { METHOD_COLOR, METHOD_SHORT, POLICY_COLOR, POLICY_LABEL, num, pct } from "../lib/format";
import "./evidence.css";

type Any = Record<string, any>;
const NAMES = ["static_solomon", "static_amazon", "target_sweep", "uncertainty_levels", "misspecification", "dynamic_solomon", "dynamic_amazon", "traveltime_model"];

export function Evidence() {
  const [data, setData] = useState<Record<string, Any>>({});
  const [status, setStatus] = useState<"loading" | "done" | "error">("loading");
  const [error, setError] = useState<string>();

  useEffect(() => {
    api.experiments().then(
      async (list) => {
        const names = list.map((e) => e.name).filter((n) => NAMES.includes(n));
        const loaded = await Promise.all(names.map((n) => api.experiment<Any>(n).then((d) => [n, d] as const)));
        setData(Object.fromEntries(loaded));
        setStatus("done");
      },
      (e) => {
        setError(e.message);
        setStatus("error");
      },
    );
  }, []);

  if (status === "loading") return <div className="page"><Progress value={0.4} message="Loading stored experiment results" /></div>;
  if (status === "error") return <div className="page"><ErrorNote>{error}</ErrorNote></div>;
  if (!Object.keys(data).length) {
    return (
      <div className="page">
        <Empty icon={<FlaskConical size={18} />} title="No experiment results yet">
          Run <code>python scripts/run_experiments.py --suite all</code> to generate the evidence base. Nothing on this page is precomputed by hand.
        </Empty>
      </div>
    );
  }

  return (
    <div className="page evidence">
      <header className="page-head">
        <div>
          <div className="eyebrow">Evidence</div>
          <h1>Does planning for uncertainty reduce late deliveries, and what does it cost?</h1>
          <p className="page-lede">
            Every figure on this page is read from experiment artifacts produced by <code>scripts/run_experiments.py</code>.
            Plans come from PyVRP; outcomes are measured by Monte Carlo simulation on a scenario stream the planners never saw.
            Variability and disruptions are synthetic; travel-time calibration uses real Amazon data.
          </p>
        </div>
        <div className="head-tags">
          <ProvTag kind="measured">Measured outputs</ProvTag>
          <ProvTag kind="synthetic">Synthetic scenarios</ProvTag>
        </div>
      </header>

      <Headline data={data} />
      {data.static_solomon && <StaticBlock exp={data.static_solomon} amazon={data.static_amazon} />}
      <div className="grid-2">
        {data.target_sweep && <TargetBlock exp={data.target_sweep} />}
        {data.misspecification && <MisspecBlock exp={data.misspecification} />}
      </div>
      {data.uncertainty_levels && <LevelsBlock exp={data.uncertainty_levels} />}
      {(data.dynamic_solomon || data.dynamic_amazon) && <DynamicBlock solomon={data.dynamic_solomon} amazon={data.dynamic_amazon} />}
      {data.traveltime_model && <TravelBlock exp={data.traveltime_model} />}
      <Reproduce data={data} />
    </div>
  );
}

function Headline({ data }: { data: Record<string, Any> }) {
  const s = data.static_solomon?.summary;
  const a = data.static_amazon?.summary;
  const d = data.dynamic_solomon?.summary;
  const cards: { k: string; v: string; sub: string; tone?: "ok" | "warn" }[] = [];
  if (s?.reliability) {
    cards.push({
      k: "Solomon · on-time stops",
      v: `${pct(s.deterministic.on_time_rate)} → ${pct(s.reliability.on_time_rate)}`,
      sub: `+${s.reliability.delta_on_time_pt.toFixed(1)} pt [${s.reliability.delta_on_time_ci.map((x: number) => x.toFixed(1)).join(", ")}] at ${s.reliability.delta_distance_pct >= 0 ? "+" : ""}${s.reliability.delta_distance_pct.toFixed(1)}% distance · ${s.reliability.n} instances`,
    });
    cards.push({
      k: "Target attainment (95%)",
      v: `${pct(s.reliability.target_attainment_rate, 0)}`,
      sub: `of instances met the target out-of-sample; baseline ${pct(s.deterministic.target_attainment_rate, 0)}`,
      tone: s.reliability.target_attainment_rate >= 0.9 ? "ok" : "warn",
    });
  }
  const byT = data.static_amazon?.summary_by_target as Record<string, Any> | undefined;
  for (const [t, sm] of Object.entries(byT ?? (a ? { "0.95": a } : {}))) {
    if (!sm?.reliability) continue;
    cards.push({
      k: `Amazon · target ${pct(Number(t), 0)}`,
      v: `${pct(sm.deterministic.on_time_rate)} → ${pct(sm.reliability.on_time_rate)}`,
      sub: `${fmtPt(sm.reliability.delta_on_time_pt)} pt at ${sm.reliability.delta_distance_pct >= 0 ? "+" : ""}${sm.reliability.delta_distance_pct.toFixed(1)}% driving time; target met on ${pct(sm.reliability.target_attainment_rate, 0)} (baseline ${pct(sm.deterministic.target_attainment_rate, 0)}) · ${sm.reliability.n} station-days`,
    });
  }
  if (d?.["deterministic+reliability"]) {
    const h = d["deterministic+hold"], r = d["deterministic+reliability"], o = d["deterministic+reoptimise"];
    cards.push({
      k: "After disruptions",
      v: `${pct(h.on_time_rate)} → ${pct(r.on_time_rate)}`,
      sub: `hold vs KAIROS replanning (re-optimise: ${pct(o.on_time_rate)}) · ${r.n} disruptions`,
    });
  }
  return (
    <section className="headline">
      {cards.map((c) => (
        <div key={c.k} className="hcard">
          <div className="eyebrow">{c.k}</div>
          <div className="hval num">{c.v}</div>
          <div className="hsub">{c.sub}</div>
          {c.tone && <StatusPill tone={c.tone}>{c.tone === "ok" ? "Reliability target generally met" : "Target not consistently met"}</StatusPill>}
        </div>
      ))}
    </section>
  );
}

/** Signed one-decimal value that never prints "-0.0". */
const fmtPt = (v: number) => {
  const r = Math.round(v * 10) / 10;
  return r === 0 ? "±0.0" : `${r > 0 ? "+" : "−"}${Math.abs(r).toFixed(1)}`;
};

/** Python's str(float): 1.0 -> "1.0", 0.75 -> "0.75" (matches artifact keys). */
const pyFloat = (v: number) => (Number.isInteger(v) ? v.toFixed(1) : String(v));

const GROUP_ORDER =["overall", "C1", "R1", "RC1", "C2", "R2", "RC2", "Amazon"];

function forestRows(exp: Any, metric: string, key = "medium|x1.0|0.95", groupLabel?: string): ForestRow[] {
  const s = exp.summaries?.[key];
  if (!s) return [];
  const entries = [...s.overall, ...s.by_group].filter((e: Any) => e.paired_vs_baseline);
  entries.sort((a: Any, b: Any) => GROUP_ORDER.indexOf(a.scope) - GROUP_ORDER.indexOf(b.scope));
  return entries.map((e: Any) => {
    const p = e.paired_vs_baseline[metric];
    return {
      group: groupLabel ?? (e.scope === "overall" ? "All instances" : e.scope),
      label: METHOD_SHORT[e.method as Method],
      color: METHOD_COLOR[e.method as Method],
      mean: p.mean,
      ci: p.ci95,
      n: p.n,
      p: p.wilcoxon_p,
    };
  });
}

function StaticBlock({ exp, amazon }: { exp: Any; amazon?: Any }) {
  const amazonRows = (metric: string) =>
    amazon
      ? (amazon.config.targets as number[]).flatMap((t) =>
          forestRows(amazon, metric, `medium|x1.0|${t}`, `Amazon · target ${pct(t, 0)}`).slice(0, 3),
        )
      : [];
  const rowsOT = [...forestRows(exp, "on_time_rate_pt"), ...amazonRows("on_time_rate_pt")];
  const rowsD = [...forestRows(exp, "distance_rel_pct"), ...amazonRows("distance_rel_pct")];
  const overall = exp.summaries["medium|x1.0|0.95"].overall as Any[];
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <div className="eyebrow">Experiment 1 · Static planning and ablation</div>
          <h3>Effect of each component against the deterministic baseline</h3>
          <p className="card-sub">
            Paired differences per instance (method − baseline), mean and 95% bootstrap CI across instances. Target 95%, medium uncertainty,
            {` ${num(exp.config.iterations)}`} PyVRP iterations per planner, {exp.config.eval_scenarios} evaluation scenarios.
            <b> Buffer</b> isolates safety buffers; <b>Selection</b> isolates scenario-based selection; <b>KAIROS</b> combines both.
          </p>
        </div>
        <Legend items={(["buffered", "saa_select", "reliability"] as Method[]).map((m) => ({ label: METHOD_SHORT[m], color: METHOD_COLOR[m] }))} />
      </div>
      <div className="grid-2 tight">
        <div>
          <div className="chart-title">On-time stops (percentage points)</div>
          <ForestPlot rows={rowsOT} unit=" pt" title="Change in on-time rate" />
        </div>
        <div>
          <div className="chart-title">Travel cost (%)</div>
          <ForestPlot rows={rowsD} unit="%" title="Change in travel cost" />
        </div>
      </div>
      <table className="dtable" style={{ marginTop: 16 }}>
        <thead>
          <tr>
            <th>Planner (all Solomon)</th><th className="r">On-time</th><th className="r">All windows met</th><th className="r">Lateness</th>
            <th className="r">Distance</th><th className="r">Vehicles</th><th className="r">Target met</th><th className="r">Runtime</th>
          </tr>
        </thead>
        <tbody>
          {overall.map((e) => (
            <tr key={e.method}>
              <td><span className="swatch" style={{ background: METHOD_COLOR[e.method as Method] }} />{METHOD_SHORT[e.method as Method]}</td>
              <td className="r num">{pct(e.mean.on_time_rate)}</td>
              <td className="r num">{pct(e.mean.p_all_on_time, 0)}</td>
              <td className="r num">{num(e.mean.lateness_total_mean, 1)}</td>
              <td className="r num">{num(e.mean.distance, 0)}</td>
              <td className="r num">{num(e.mean.n_routes, 1)}</td>
              <td className="r num">{pct(e.target_attainment_rate, 0)}</td>
              <td className="r num">{num(e.runtime_s_mean, 1)} s</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="foot">{exp.n_runs} runs, {exp.n_failed} failed{exp.n_failed ? " (listed in the artifact)" : ""}. Runtimes measured with {exp.config.workers} parallel workers.</p>
    </section>
  );
}

function TargetBlock({ exp }: { exp: Any }) {
  const targets: number[] = exp.config.targets;
  const pts = targets.map((t) => {
    const e = exp.summaries[`medium|x1.0|${t}`].overall.find((x: Any) => x.method === "reliability");
    return { t, ot: e.mean.on_time_rate, att: e.target_attainment_rate, cost: e.paired_vs_baseline.distance_rel_pct.mean };
  });
  const base = exp.summaries[`medium|x1.0|${targets[0]}`].overall.find((x: Any) => x.method === "deterministic");
  return (
    <section className="card">
      <div className="eyebrow">Experiment 2 · Target control</div>
      <h3>The reliability target changes the plan</h3>
      <p className="card-sub">Achieved out-of-sample on-time rate against the requested target ({exp.config.instances.length} Solomon instances). Dashed line: achieved = target.</p>
      <LineChart
        title="Achieved versus requested reliability"
        series={[
          { label: "KAIROS", color: METHOD_COLOR.reliability, points: pts.map((p) => ({ x: p.t, y: p.ot, note: `met on ${pct(p.att, 0)} of instances · cost ${p.cost >= 0 ? "+" : ""}${p.cost.toFixed(1)}%` })) },
          { label: "Baseline", color: METHOD_COLOR.deterministic, points: pts.map((p) => ({ x: p.t, y: base.mean.on_time_rate })), dashed: true },
        ]}
        diagonal
        xFormat={(v) => pct(v, 0)}
        yFormat={(v) => pct(v, 0)}
        xLabel="Requested target"
      />
      <table className="dtable compact">
        <thead><tr><th>Target</th><th className="r">Achieved</th><th className="r">Met on</th><th className="r">Cost vs baseline</th></tr></thead>
        <tbody>{pts.map((p) => <tr key={p.t}><td className="num">{pct(p.t, 0)}</td><td className="r num">{pct(p.ot)}</td><td className="r num">{pct(p.att, 0)}</td><td className="r num">{p.cost >= 0 ? "+" : ""}{p.cost.toFixed(1)}%</td></tr>)}</tbody>
      </table>
    </section>
  );
}

function MisspecBlock({ exp }: { exp: Any }) {
  const scales: number[] = exp.config.planner_scales;
  const target = exp.config.targets[0];
  const pts = scales.map((s) => {
    const e = exp.summaries[`medium|x${pyFloat(s)}|${target}`];
    const r = e.overall.find((x: Any) => x.method === "reliability");
    return { s, ot: r.mean.on_time_rate, att: r.target_attainment_rate, cost: r.paired_vs_baseline.distance_rel_pct.mean };
  });
  return (
    <section className="card">
      <div className="eyebrow">Experiment 3 · Robustness</div>
      <h3>When the planner's uncertainty model is wrong</h3>
      <p className="card-sub">The planner assumes dispersion scaled by the factor shown; the evaluation world stays at the medium setting. Below 1 means the planner underestimates risk.</p>
      <LineChart
        title="Attainment under misspecification"
        series={[
          { label: "Achieved", color: METHOD_COLOR.reliability, points: pts.map((p) => ({ x: p.s, y: p.ot, note: `target met on ${pct(p.att, 0)} · cost ${p.cost >= 0 ? "+" : ""}${p.cost.toFixed(1)}%` })) },
          { label: "Target", color: "#0b1324", points: pts.map((p) => ({ x: p.s, y: target })), dashed: true },
        ]}
        xFormat={(v) => `×${v.toFixed(2)}`}
        yFormat={(v) => pct(v, 0)}
        xLabel="Planner-assumed dispersion / true dispersion"
      />
      <table className="dtable compact">
        <thead><tr><th>Assumed ×</th><th className="r">Achieved</th><th className="r">Met on</th><th className="r">Cost</th></tr></thead>
        <tbody>{pts.map((p) => <tr key={p.s}><td className="num">×{p.s}</td><td className="r num">{pct(p.ot)}</td><td className="r num">{pct(p.att, 0)}</td><td className="r num">{p.cost >= 0 ? "+" : ""}{p.cost.toFixed(1)}%</td></tr>)}</tbody>
      </table>
    </section>
  );
}

function LevelsBlock({ exp }: { exp: Any }) {
  const levels: string[] = exp.config.levels;
  return (
    <section className="card">
      <div className="eyebrow">Experiment 4 · Sensitivity</div>
      <h3>Gains depend on how uncertain operations are</h3>
      <p className="card-sub">Same instances under low, medium and high synthetic variability; target 95%.</p>
      <table className="dtable">
        <thead>
          <tr><th>Variability</th><th>Planner</th><th className="r">On-time</th><th className="r">Δ on-time vs baseline</th><th className="r">Δ distance</th><th className="r">Target met</th></tr>
        </thead>
        <tbody>
          {levels.flatMap((lv) =>
            (exp.summaries[`${lv}|x1.0|0.95`].overall as Any[]).map((e, i) => (
              <tr key={lv + e.method}>
                <td>{i === 0 ? <b style={{ textTransform: "capitalize" }}>{lv}</b> : ""}</td>
                <td><span className="swatch" style={{ background: METHOD_COLOR[e.method as Method] }} />{METHOD_SHORT[e.method as Method]}</td>
                <td className="r num">{pct(e.mean.on_time_rate)}</td>
                <td className="r num">{e.paired_vs_baseline ? `${e.paired_vs_baseline.on_time_rate_pt.mean >= 0 ? "+" : ""}${e.paired_vs_baseline.on_time_rate_pt.mean.toFixed(1)} pt` : "—"}</td>
                <td className="r num">{e.paired_vs_baseline ? `${e.paired_vs_baseline.distance_rel_pct.mean >= 0 ? "+" : ""}${e.paired_vs_baseline.distance_rel_pct.mean.toFixed(1)}%` : "—"}</td>
                <td className="r num">{pct(e.target_attainment_rate, 0)}</td>
              </tr>
            )),
          )}
        </tbody>
      </table>
    </section>
  );
}

const COMBOS: { key: string; base: string; policy: "hold" | "reoptimise" | "reliability"; label: string }[] = [
  { key: "deterministic+hold", base: "Baseline plan", policy: "hold", label: "Hold + insert" },
  { key: "deterministic+reoptimise", base: "Baseline plan", policy: "reoptimise", label: "Re-optimise" },
  { key: "deterministic+reliability", base: "Baseline plan", policy: "reliability", label: "KAIROS replan" },
  { key: "reliability+hold", base: "KAIROS plan", policy: "hold", label: "Hold + insert" },
  { key: "reliability+reoptimise", base: "KAIROS plan", policy: "reoptimise", label: "Re-optimise" },
  { key: "reliability+reliability", base: "KAIROS plan", policy: "reliability", label: "KAIROS replan" },
];

function DynamicBlock({ solomon, amazon }: { solomon?: Any; amazon?: Any }) {
  const [bench, setBench] = useState<"solomon" | "amazon">(solomon ? "solomon" : "amazon");
  const exp = bench === "solomon" ? solomon : amazon;
  const events: string[] = exp?.config.events ?? [];
  const cells: Any[] = exp?.cells ?? [];
  const cell = (bm: string, pol: string, ev: string) => cells.find((c) => c.base_method === bm && c.policy === pol && c.event === ev);
  const rows: ForestRow[] = useMemo(
    () =>
      COMBOS.filter((c) => c.key !== "deterministic+hold").map((c) => {
        const [bm, pol] = c.key.split("+");
        const p = cell(bm, pol, "all")?.paired_vs_det_hold?.on_time_rate_pt;
        return { group: c.base, label: c.label, color: POLICY_COLOR[c.policy], mean: p?.mean ?? 0, ci: p?.ci95 ?? [0, 0], n: p?.n, p: p?.wilcoxon_p };
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [exp],
  );
  if (!exp) return null;
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <div className="eyebrow">Experiment 5 · Dynamic replanning under disruptions</div>
          <h3>Which matters more: the initial plan or the replanning policy?</h3>
          <p className="card-sub">
            Full factorial: base plan (baseline or KAIROS) × replanning policy, {events.length} synthetic event types × {exp.config.repeats} seeded repetitions per instance.
            Metrics cover the residual horizon after the event, paired against the baseline plan with hold-and-insert repair.
          </p>
        </div>
        <div className="seg-wrap">
          {solomon && amazon && (
            <div className="seg seg-sm" role="radiogroup" aria-label="Benchmark">
              <button role="radio" aria-checked={bench === "solomon"} className={bench === "solomon" ? "seg-item active" : "seg-item"} onClick={() => setBench("solomon")}>Solomon</button>
              <button role="radio" aria-checked={bench === "amazon"} className={bench === "amazon" ? "seg-item active" : "seg-item"} onClick={() => setBench("amazon")}>Amazon</button>
            </div>
          )}
        </div>
      </div>
      <div className="stack">
        <div className="half">
          <div className="chart-title">Δ on-time stops vs baseline plan + hold (pt)</div>
          <ForestPlot rows={rows} unit=" pt" title="Dynamic policy effects" />
          <Legend items={(["hold", "reoptimise", "reliability"] as const).map((p) => ({ label: POLICY_LABEL[p], color: POLICY_COLOR[p] }))} />
        </div>
        <div className="scroll-x">
          <table className="dtable compact">
            <thead>
              <tr><th>Base · policy</th>{events.map((e) => <th key={e} className="r">{e.replace("_", " ")}</th>)}<th className="r">replan s</th></tr>
            </thead>
            <tbody>
              {COMBOS.map((c) => {
                const [bm, pol] = c.key.split("+");
                return (
                  <tr key={c.key}>
                    <td><span className="swatch" style={{ background: POLICY_COLOR[c.policy] }} />{c.base === "KAIROS plan" ? "KAIROS" : "Base"} · {c.label}</td>
                    {events.map((e) => <td key={e} className="r num">{pct(cell(bm, pol, e)?.mean.on_time_rate)}</td>)}
                    <td className="r num">{num(cell(bm, pol, "all")?.mean.runtime_s, 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="foot">Cells: mean residual on-time rate. {exp.n_runs} policy evaluations, {exp.n_failed} failed.</p>
        </div>
      </div>
    </section>
  );
}

function TravelBlock({ exp }: { exp: Any }) {
  const cov: Any[] = exp.test.coverage;
  const base: Any[] = exp.baseline_speed_fit.coverage;
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <div className="eyebrow">Experiment 6 · Real-data uncertainty calibration</div>
          <h3>Travel-time estimates with calibrated intervals (Amazon)</h3>
          <p className="card-sub">
            LightGBM quantile regression on observed average travel times; conformal calibration on dates {exp.data.split_dates.calibration[0]}–{exp.data.split_dates.calibration[1]};
            evaluated on later dates {exp.data.split_dates.test[0]}–{exp.data.split_dates.test[1]} ({num(exp.data.n_test_arcs)} arcs). Used for cross-route and urgent-order arcs.
          </p>
        </div>
        <ProvTag kind="observed">Real outcome data</ProvTag>
      </div>
      <div className="grid-2 tight">
        <LineChart
          title="Interval coverage: nominal versus empirical"
          series={[
            { label: "Conformal", color: METHOD_COLOR.reliability, points: cov.map((r) => ({ x: r.nominal, y: r.conformal_coverage, note: `median width ×${(1 + r.conformal_rel_width).toFixed(2)}` })) },
            { label: "Raw quantiles", color: METHOD_COLOR.buffered, points: cov.map((r) => ({ x: r.nominal, y: r.raw_coverage })) },
            { label: "Speed baseline", color: METHOD_COLOR.deterministic, points: base.map((r) => ({ x: r.nominal, y: r.coverage, note: `median width ×${(1 + r.rel_width).toFixed(2)}` })) },
          ]}
          diagonal
          xDomain={[0.45, 1]}
          yDomain={[0.45, 1]}
          xFormat={(v) => pct(v, 0)}
          yFormat={(v) => pct(v, 0)}
          xLabel="Nominal coverage"
        />
        <table className="dtable compact">
          <thead><tr><th>Metric (test dates)</th><th className="r">Model</th><th className="r">Speed baseline</th></tr></thead>
          <tbody>
            <tr><td>Mean absolute error</td><td className="r num">{num(exp.test.mae_s, 1)} s</td><td className="r num">{num(exp.baseline_speed_fit.mae_s, 1)} s</td></tr>
            <tr><td>Median absolute % error</td><td className="r num">{pct(exp.test.median_ape)}</td><td className="r num">{pct(exp.baseline_speed_fit.median_ape)}</td></tr>
            {cov.map((r, i) => (
              <tr key={r.nominal}>
                <td>{pct(r.nominal, 0)} interval coverage (width)</td>
                <td className="r num">{pct(r.conformal_coverage)} (×{(1 + r.conformal_rel_width).toFixed(2)})</td>
                <td className="r num">{pct(base[i].coverage)} (×{(1 + base[i].rel_width).toFixed(2)})</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="caveats">{(exp.caveats as string[]).map((c) => <li key={c}>{c}</li>)}</ul>
    </section>
  );
}

function Reproduce({ data }: { data: Record<string, Any> }) {
  return (
    <section className="card reproduce">
      <div className="card-head">
        <div>
          <div className="eyebrow">Reproduce</div>
          <h3>Regenerate every number on this page</h3>
        </div>
        <Terminal size={18} />
      </div>
      <pre className="code">{`python scripts/prepare_amazon.py          # ingest, validate, split by date
python scripts/train_traveltime.py        # LightGBM quantiles + conformal calibration
python scripts/build_amazon_instances.py  # merged station-day instances (test dates)
python scripts/run_experiments.py --suite all --workers 8`}</pre>
      <div className="artifacts">
        {Object.entries(data).map(([k, v]) => (
          <span key={k} className="artifact"><code>artifacts/experiments/{k}.json</code> <span className="muted">{v.created?.slice(0, 16).replace("T", " ")}</span></span>
        ))}
      </div>
    </section>
  );
}
