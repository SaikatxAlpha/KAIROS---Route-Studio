import { useMemo } from "react";
import { ArrowDownRight, ArrowUpRight, Gauge, Info } from "lucide-react";
import type { Method, PlanResult } from "../../api/types";
import { FrontierChart } from "../../components/charts/FrontierChart";
import { Empty, ErrorNote, ProvTag, StatusPill } from "../../components/ui";
import { METHOD_COLOR, METHOD_SHORT, makeCostFormat, makeDurationFormat, num, pct, signedPct } from "../../lib/format";
import { useStore } from "../../state/store";

export function DecisionPanel() {
  const { compare, instance, settings } = useStore();
  const summary = instance?.summary;
  const fmtCost = useMemo(() => makeCostFormat(summary), [summary]);
  const fmtDur = useMemo(() => makeDurationFormat(summary), [summary]);
  const r = compare.result;

  if (compare.status === "error") {
    return (
      <aside className="decision"><ErrorNote>{compare.error}</ErrorNote></aside>
    );
  }
  if (!r) {
    return (
      <aside className="decision" aria-label="Decision comparison">
        <div className="eyebrow">03 · Decision</div>
        <Empty icon={<Gauge size={18} />} title={compare.status === "running" ? "Solving and simulating" : "Compare planners"}>
          {compare.status === "running"
            ? compare.message
            : `Solves the deterministic baseline and the reliability-aware planner on the same budget, then measures both on ${settings.evalScenarios} unseen scenarios.`}
        </Empty>
        <ol className="howto">
          <li><b>Baseline</b> plans on expected travel and service times.</li>
          <li><b>KAIROS</b> builds a ladder of buffered candidates and keeps the cheapest one whose estimated on-time rate meets the target.</li>
          <li>Both are scored on a <b>disjoint</b> scenario stream with common random numbers.</li>
        </ol>
      </aside>
    );
  }

  const base = r.plans.deterministic!;
  const methods = (Object.keys(r.plans) as Method[]).filter((m) => m !== "deterministic");
  const hero = (r.plans.reliability ? "reliability" : methods[0]) as Method | undefined;
  const heroPlan = hero ? r.plans[hero]! : undefined;
  const paired = hero ? r.paired_vs_deterministic[hero] : undefined;

  return (
    <aside className="decision" aria-label="Decision comparison">
      <div className="eyebrow">03 · Decision</div>
      {heroPlan && paired && <Verdict base={base} plan={heroPlan} target={r.target} costDelta={paired.distance.relative} method={hero!} />}

      <table className="cmp">
        <thead>
          <tr>
            <th />
            <th className="r"><span className="swatch" style={{ background: METHOD_COLOR.deterministic }} />{METHOD_SHORT.deterministic}</th>
            {methods.map((m) => (
              <th key={m} className="r"><span className="swatch" style={{ background: METHOD_COLOR[m] }} />{METHOD_SHORT[m]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          <Row label="On-time stops" hint="Share of windowed stops reached before the window closes (mean over scenarios)" base={pct(base.evaluation.on_time_rate)} values={methods.map((m) => ({ v: pct(r.plans[m]!.evaluation.on_time_rate), d: r.paired_vs_deterministic[m]!.on_time_rate, good: "up", fmt: (x: number) => `${signedPct(x)} pt` }))} strong />
          <Row label="All windows met" hint="Probability that a scenario has zero late stops" base={pct(base.evaluation.p_all_on_time, 0)} values={methods.map((m) => ({ v: pct(r.plans[m]!.evaluation.p_all_on_time, 0) }))} />
          <Row label="Expected lateness" hint="Total minutes/units late, mean over scenarios" base={fmtDur(base.evaluation.lateness_total_mean)} values={methods.map((m) => ({ v: fmtDur(r.plans[m]!.evaluation.lateness_total_mean), d: r.paired_vs_deterministic[m]!.lateness_total, good: "down", fmt: (x: number) => (x > 0 ? "+" : "−") + fmtDur(Math.abs(x)) }))} />
          <Row label="Travel cost" hint={summary?.distance_unit === "s" ? "Expected driving time (dataset has no road distances)" : "Euclidean distance"} base={fmtCost(base.evaluation.distance)} values={methods.map((m) => ({ v: fmtCost(r.plans[m]!.evaluation.distance), rel: r.paired_vs_deterministic[m]!.distance.relative }))} />
          <Row label="Vehicles used" base={num(base.evaluation.n_routes)} values={methods.map((m) => ({ v: num(r.plans[m]!.evaluation.n_routes) }))} />
          <Row label="Overtime risk" hint="Probability any vehicle returns after shift end" base={pct(base.evaluation.p_overtime, 0)} values={methods.map((m) => ({ v: pct(r.plans[m]!.evaluation.p_overtime, 0) }))} />
          <Row label="Compute" base={`${num(base.runtime_total_s, 1)} s`} values={methods.map((m) => ({ v: `${num(r.plans[m]!.runtime_total_s, 1)} s` }))} />
        </tbody>
      </table>
      <p className="cmp-foot">
        Deltas are paired over {r.eval_scenarios} common scenarios; brackets show 95% CI. {base.solver.feasible ? "" : "Baseline plan infeasible under nominal times. "}
      </p>

      {heroPlan && heroPlan.candidates.length > 0 && (
        <div className="frontier-block">
          <div className="block-head">
            <div className="eyebrow">Why this plan</div>
            <span className="muted small">in-sample estimates</span>
          </div>
          <FrontierChart
            candidates={heroPlan.candidates}
            target={r.target}
            baseline={{ distance: base.evaluation.distance, onTime: base.evaluation.on_time_rate }}
            chosenOos={{ distance: heroPlan.evaluation.distance, onTime: heroPlan.evaluation.on_time_rate }}
            formatCost={fmtCost}
          />
          <div className="frontier-legend">
            <span><i className="dot" style={{ background: "#1f47d6" }} /> chosen candidate</span>
            <span><i className="dot hollow" /> other candidates</span>
            <span><i className="diamond" /> chosen, out-of-sample</span>
            <span><i className="dot" style={{ background: "#eb6834" }} /> baseline, out-of-sample</span>
          </div>
          <Explain plan={heroPlan} target={r.target} fmtCost={fmtCost} />
        </div>
      )}

      <div className="prov-foot">
        <ProvTag kind="algorithm">Plans: PyVRP</ProvTag>
        <ProvTag kind="measured">Metrics: simulated, out-of-sample</ProvTag>
        <ProvTag kind="synthetic">Scenarios: synthetic</ProvTag>
      </div>
    </aside>
  );
}

function Verdict({ base, plan, target, costDelta, method }: { base: PlanResult; plan: PlanResult; target: number; costDelta: number; method: Method }) {
  const ot = plan.evaluation.on_time_rate;
  const met = ot >= target;
  return (
    <div className={`verdict ${met ? "ok" : "warn"}`}>
      <div className="verdict-top">
        <StatusPill tone={met ? "ok" : "warn"}>{met ? "Target met out-of-sample" : "Target missed out-of-sample"}</StatusPill>
      </div>
      <div className="verdict-figures">
        <div>
          <div className="verdict-big num">{pct(ot)}</div>
          <div className="verdict-label">{METHOD_SHORT[method]} on-time</div>
        </div>
        <div className="verdict-vs">
          <div className="num">{pct(base.evaluation.on_time_rate)}</div>
          <div className="verdict-label">baseline</div>
        </div>
      </div>
      <p className="verdict-text">
        Travel cost {costDelta >= 0 ? "rises" : "falls"} <b className="num">{signedPct(costDelta)}%</b> against the baseline
        {plan.target_attained === false && "; no candidate met the target in-sample, so the most reliable one was kept"}.
      </p>
    </div>
  );
}

function Row({
  label,
  hint,
  base,
  values,
  strong,
}: {
  label: string;
  hint?: string;
  base: string;
  values: { v: string; d?: { mean: number; ci95: [number, number] }; good?: "up" | "down"; fmt?: (x: number) => string; rel?: number }[];
  strong?: boolean;
}) {
  return (
    <tr className={strong ? "strong" : ""}>
      <th scope="row">
        <span>{label}</span>
        {hint && <span className="hint" title={hint} aria-label={hint}><Info size={11} /></span>}
      </th>
      <td className="r num">{base}</td>
      {values.map((x, i) => {
        let delta = null;
        if (x.d && x.fmt) {
          const significant = x.d.ci95[0] > 0 || x.d.ci95[1] < 0;
          const better = x.good === "up" ? x.d.mean > 0 : x.d.mean < 0;
          delta = (
            <span className={`delta ${significant ? (better ? "good" : "bad") : "flat"}`} title={`95% CI [${x.fmt(x.d.ci95[0])}, ${x.fmt(x.d.ci95[1])}]`}>
              {x.d.mean > 0 ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
              {x.fmt(x.d.mean)}
            </span>
          );
        } else if (x.rel != null) {
          delta = <span className="delta flat">{signedPct(x.rel)}%</span>;
        }
        return (
          <td key={i} className="r">
            <div className="num">{x.v}</div>
            {delta}
          </td>
        );
      })}
    </tr>
  );
}

function Explain({ plan, target, fmtCost }: { plan: PlanResult; target: number; fmtCost: (c: number) => string }) {
  const meeting = plan.candidates.filter((c) => c.in_sample_on_time_rate >= target);
  const chosen = plan.candidates.find((c) => c.chosen);
  if (!chosen) return null;
  return (
    <p className="explain">
      {plan.candidates.length} candidates were solved with safety buffers β ∈ {"{"}
      {plan.candidates.map((c) => c.beta.toFixed(2)).join(", ")}
      {"}"} standard deviations. {meeting.length} met the {pct(target, 1)} target on {plan.config.planning_scenarios} in-sample scenarios
      {meeting.length > 0 ? <>; the cheapest of them (β = {chosen.beta.toFixed(2)}, {fmtCost(chosen.distance)}) was selected.</> : <>; the most reliable (β = {chosen.beta.toFixed(2)}) was kept.</>}
    </p>
  );
}
