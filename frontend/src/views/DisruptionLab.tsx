import { useEffect, useMemo, useState } from "react";
import { CloudRain, MapPin, PackagePlus, Play, Timer, TrafficCone, Wrench, Zap } from "lucide-react";
import { api, waitForJob } from "../api/client";
import type { DisruptionEvent, DisruptionResult, EventType, Method, Policy, Stop } from "../api/types";
import { RouteMap, type MapRoute, type StopStyle } from "../components/map/RouteMap";
import { Button, Empty, ErrorNote, Field, Legend, Progress, ProvTag, Segmented, Slider, StatusPill } from "../components/ui";
import {
  METHOD_SHORT,
  POLICY_COLOR,
  POLICY_LABEL,
  POLICY_SHORT,
  VEHICLE_COLORS,
  makeCostFormat,
  makeDurationFormat,
  makeTimeFormat,
  num,
  pct,
} from "../lib/format";
import { RISK_BANDS, riskColor } from "../lib/risk";
import { useStore, type RunState } from "../state/store";
import { NEUTRAL_ROUTE, stopTooltip } from "./shared";
import "./disrupt.css";

const EVENTS: { type: EventType; label: string; icon: typeof Zap; blurb: string }[] = [
  { type: "traffic", label: "Traffic delay", icon: TrafficCone, blurb: "Slower travel on arcs touching an area" },
  { type: "breakdown", label: "Vehicle breakdown", icon: Wrench, blurb: "A vehicle stops; its stops need a new owner" },
  { type: "urgent_order", label: "Urgent order", icon: PackagePlus, blurb: "A new stop with a tight window appears" },
  { type: "service_shock", label: "Service shock", icon: Timer, blurb: "Stops in an area take longer to serve" },
  { type: "weather", label: "Adverse weather", icon: CloudRain, blurb: "Travel and service slow down everywhere" },
];

const ALL_POLICIES: Policy[] = ["hold", "reoptimise", "reliability"];

export function DisruptionLab({ onNeedPlan }: { onNeedPlan: () => void }) {
  const { instance, compare, settings } = useStore();
  const summary = instance?.summary;
  const fmt = useMemo(() => makeTimeFormat(summary), [summary]);
  const fmtDur = useMemo(() => makeDurationFormat(summary), [summary]);
  const fmtCost = useMemo(() => makeCostFormat(summary), [summary]);
  const plans = compare.result?.plans;
  const available = plans ? (Object.keys(plans) as Method[]) : [];
  const [baseMethod, setBaseMethod] = useState<Method>("deterministic");
  const plan = plans?.[baseMethod];

  const geo = summary?.coord_system === "wgs84";
  const horizon = summary ? summary.horizon : 1;
  const [type, setType] = useState<EventType>("traffic");
  const [timeFrac, setTimeFrac] = useState(0.3);
  const [factor, setFactor] = useState(1.6);
  const [scope, setScope] = useState<"area" | "all">("area");
  const [center, setCenter] = useState<[number, number] | null>(null);
  const [radius, setRadius] = useState(geo ? 2 : 20);
  const [vehicle, setVehicle] = useState(0);
  const [location, setLocation] = useState<[number, number] | null>(null);
  const [windowFrac, setWindowFrac] = useState(0.15);
  const [policies, setPolicies] = useState<Policy[]>(ALL_POLICIES);
  const [run, setRun] = useState<RunState<DisruptionResult>>({ status: "idle", progress: 0, message: "" });
  const [shown, setShown] = useState<Policy>("reliability");

  useEffect(() => {
    setRadius(geo ? 2 : 20);
    setCenter(null);
    setLocation(null);
    setRun({ status: "idle", progress: 0, message: "" });
  }, [summary?.id, geo]);

  useEffect(() => {
    if (plans && !plans[baseMethod]) setBaseMethod("deterministic");
  }, [plans, baseMethod]);

  if (!instance || !summary) return <div className="page"><Progress value={0.3} message="Loading instance" /></div>;
  if (!plan) {
    return (
      <div className="page">
        <Empty icon={<Zap size={18} />} title="No plan in operation">
          The Disruption Lab perturbs a plan that is already executing. Run a comparison in Route Studio first, then return here.
          <div style={{ marginTop: 14 }}>
            <Button variant="primary" onClick={onNeedPlan}>Go to Route Studio</Button>
          </div>
        </Empty>
      </div>
    );
  }

  const tau = Math.round(timeFrac * horizon);
  const needsArea = type === "traffic" || type === "service_shock";
  const pickMode = type === "urgent_order" ? "location" : needsArea && scope === "area" ? "center" : null;
  const canRun =
    policies.length > 0 &&
    (type !== "urgent_order" || location != null) &&
    (!needsArea || scope === "all" || center != null);

  const buildEvent = (): DisruptionEvent => {
    const ev: DisruptionEvent = { type, time: tau };
    if (type === "traffic" || type === "weather" || type === "service_shock") ev.factor = factor;
    if (needsArea && scope === "area" && center) {
      ev.center = center;
      ev.radius = radius;
    }
    if (type === "breakdown") ev.vehicle = vehicle;
    if (type === "urgent_order" && location) {
      ev.location = location;
      ev.window = Math.max(1, windowFrac * horizon);
      ev.service = median(instance.stops.slice(1).map((s) => s.service));
      ev.demand = Math.min(median(instance.stops.slice(1).map((s) => s.demand)), summary.capacity);
    }
    return ev;
  };

  const inject = async () => {
    setRun({ status: "running", progress: 0, message: "Submitting event" });
    try {
      const job = await api.disrupt({
        plan_id: plan.plan_id,
        event: buildEvent(),
        policies,
        target: settings.target,
        iterations: Math.min(settings.iterations, 2000),
        seed: settings.seed,
        eval_scenarios: settings.evalScenarios,
      });
      const result = await waitForJob<DisruptionResult>(job, (j) => setRun((r) => ({ ...r, progress: j.progress, message: j.message })));
      setRun({ status: "done", progress: 1, message: "Complete", result });
      setShown(policies.includes("reliability") ? "reliability" : policies[policies.length - 1]);
    } catch (e: any) {
      setRun({ status: "error", progress: 0, message: "", error: e.message ?? String(e) });
    }
  };

  const res = run.result;
  const outcome = res?.policies[shown];

  // ---------- map model ----------
  const extraStops: Stop[] = res?.new_stop
    ? [{
        index: res.new_stop.index, id: "URGENT", x: res.new_stop.x, y: res.new_stop.y, is_depot: false,
        service: res.new_stop.service, tw_early: res.new_stop.tw_early, tw_late: res.new_stop.tw_late,
        has_tw: true, demand: 0, zone: null, tw_source: "synthetic",
      }]
    : [];
  const nOrig = plan.routes.length;
  const color = (v: number) => (v < 0 || v >= 1000 ? "#0b1324" : nOrig <= VEHICLE_COLORS.length ? VEHICLE_COLORS[v] : NEUTRAL_ROUTE);

  let routes: MapRoute[];
  let styleFor: (s: Stop) => StopStyle;
  const completed = new Set(res?.state.vehicles.flatMap((v) => v.completed) ?? []);
  if (res && outcome) {
    const profiles = new Map(outcome.stop_profiles.map((p) => [p.node, p]));
    const moved = new Set(outcome.diff.moved.map((m) => m.stop));
    routes = outcome.routes.map((r, i) => ({
      key: `p${i}`,
      nodes: [r.start_node, ...r.stops, 0],
      color: color(r.vehicle),
      dashed: r.vehicle < 0,
    }));
    // faded trail of completed work
    res.state.vehicles.forEach((v) => {
      if (v.completed.length) routes.unshift({ key: `done${v.route_index}`, nodes: [0, ...v.completed, ...(v.committed != null ? [v.committed] : [])], color: "#b8bdc6", emphasis: "dim" });
    });
    styleFor = (s) => {
      if (completed.has(s.index)) return { fill: "#c9cdd4", r: 3 };
      const p = profiles.get(s.index);
      return { fill: p ? riskColor(p.p_late) : "#9aa1af", r: 4.5, ring: moved.has(s.index) ? "#1f47d6" : undefined };
    };
  } else {
    routes = plan.routes.map((r, i) => ({ key: `r${i}`, nodes: [0, ...r.stops, 0], color: color(i), emphasis: type === "breakdown" && i !== vehicle ? "dim" : "normal" }));
    const own = new Map<number, number>();
    plan.routes.forEach((r, i) => r.stops.forEach((s) => own.set(s, i)));
    styleFor = (s) => ({ fill: color(own.get(s.index) ?? 0), r: 3.8, opacity: type === "breakdown" && own.get(s.index) !== vehicle ? 0.35 : 1 });
  }

  const overlay = {
    circle: needsArea && scope === "area" && center ? { x: center[0], y: center[1], radius } : undefined,
    marker: !res && type === "urgent_order" && location ? { x: location[0], y: location[1], label: "Urgent" } : undefined,
  };

  return (
    <div className="lab">
      <aside className="rail lab-rail" aria-label="Event composer">
        <div className="rail-section">
          <div className="eyebrow">Plan in operation</div>
          <Segmented<Method> label="Plan in operation" value={baseMethod} onChange={(m) => { setBaseMethod(m); setRun({ status: "idle", progress: 0, message: "" }); }} options={available.map((m) => ({ value: m, label: METHOD_SHORT[m] }))} />
          <div className="muted small">{summary.name} · {plan.routes.length} routes · {fmtCost(plan.evaluation.distance)}</div>
        </div>
        <div className="rail-section">
          <div className="eyebrow">Event</div>
          <div className="event-grid" role="radiogroup" aria-label="Event type">
            {EVENTS.map(({ type: t, label, icon: Icon, blurb }) => (
              <button key={t} role="radio" aria-checked={type === t} className={type === t ? "event-card active" : "event-card"} onClick={() => setType(t)} title={blurb}>
                <Icon size={16} />
                <span>{label}</span>
              </button>
            ))}
          </div>
          <p className="field-hint">{EVENTS.find((e) => e.type === type)!.blurb}. Events are synthetic and user-configured.</p>
          <Field label="Occurs at" aside={<span className="num strong">{fmt(tau)}</span>}>
            <Slider label="Event time" value={timeFrac} min={0.05} max={0.85} step={0.01} onChange={setTimeFrac} format={() => fmt(tau)} />
          </Field>
          {(type === "traffic" || type === "weather" || type === "service_shock") && (
            <Field label={type === "service_shock" ? "Service time multiplier" : "Travel time multiplier"} aside={<span className="num strong">×{factor.toFixed(2)}</span>}>
              <Slider label="Multiplier" value={factor} min={1.1} max={type === "weather" ? 2.0 : 3.0} step={0.05} onChange={setFactor} format={(v) => `x${v.toFixed(2)}`} />
            </Field>
          )}
          {needsArea && (
            <Field label="Affected area" hint={scope === "area" ? (center ? "Click the map again to move the area." : "Click the map to place the area centre.") : "Applies to every stop."}>
              <Segmented label="Affected area" size="sm" value={scope} onChange={setScope} options={[{ value: "area", label: "Area" }, { value: "all", label: "Whole region" }]} />
              {scope === "area" && (
                <>
                  <div className="field-head" style={{ marginTop: 4 }}><span className="field-label">Radius</span><span className="num strong">{geo ? `${radius.toFixed(1)} km` : `${radius.toFixed(0)} u`}</span></div>
                  <Slider label="Radius" value={radius} min={geo ? 0.5 : 5} max={geo ? 8 : 60} step={geo ? 0.1 : 1} onChange={setRadius} />
                </>
              )}
            </Field>
          )}
          {type === "breakdown" && (
            <Field label="Vehicle" hint="Its committed and remaining stops become orphaned. Packages are assumed transferable.">
              <select className="input" value={vehicle} onChange={(e) => setVehicle(Number(e.target.value))} aria-label="Vehicle to break down">
                {plan.routes.map((r, i) => <option key={i} value={i}>Vehicle {i + 1} · {r.stops.length} stops</option>)}
              </select>
            </Field>
          )}
          {type === "urgent_order" && (
            <Field label="Location & window" hint={location ? `Placed at ${location[1].toFixed(4)}, ${location[0].toFixed(4)}. Click to move.` : "Click the map to place the new stop."}>
              <div className="field-head"><span className="field-label">Window width</span><span className="num strong">{fmtDur(windowFrac * horizon)}</span></div>
              <Slider label="Window width" value={windowFrac} min={0.05} max={0.4} step={0.01} onChange={setWindowFrac} />
              {geo && <span className="field-hint">Travel times to the new stop come from the calibrated travel-time model.</span>}
            </Field>
          )}
          <Field label="Policies compared">
            <div className="method-checks">
              {ALL_POLICIES.map((p) => (
                <label key={p} className="check">
                  <input type="checkbox" checked={policies.includes(p)} onChange={() => setPolicies((ps) => (ps.includes(p) ? ps.filter((x) => x !== p) : [...ps, p]))} />
                  <span className="check-swatch" style={{ background: POLICY_COLOR[p] }} />
                  {POLICY_LABEL[p]}
                </label>
              ))}
            </div>
          </Field>
        </div>
        <div className="rail-run">
          {run.status === "running" ? (
            <Progress value={run.progress} message={run.message} />
          ) : (
            <Button variant="primary" size="lg" icon={<Play size={16} />} onClick={inject} disabled={!canRun}>Inject and replan</Button>
          )}
          <p className="rail-foot">Residual metrics on {settings.evalScenarios} out-of-sample scenarios</p>
        </div>
      </aside>

      <section className="studio-main">
        <header className="canvas-head">
          <div className="canvas-title">
            <div className="eyebrow">Disruption Lab · {summary.name}</div>
            <h1>{res ? res.description : EVENTS.find((e) => e.type === type)!.label}</h1>
          </div>
          <div className="canvas-tags">
            <ProvTag kind="synthetic">Synthetic event</ProvTag>
            {res && <ProvTag kind="algorithm">Replanned by PyVRP</ProvTag>}
          </div>
        </header>
        {res && (
          <div className="canvas-toolbar">
            <Segmented<Policy> label="Policy shown" value={shown} onChange={setShown} options={(Object.keys(res.policies) as Policy[]).map((p) => ({ value: p, label: POLICY_LABEL[p] }))} />
            <span className="toolbar-note">At {fmt(res.tau)}: {res.state.n_completed} stops completed · {res.state.vehicles.filter((v) => v.status === "en_route").length} vehicles en route</span>
          </div>
        )}
        <div className="canvas-map">
          <RouteMap
            coordSystem={summary.coord_system}
            stops={instance.stops}
            extraStops={extraStops}
            routes={routes}
            styleFor={styleFor}
            overlay={overlay}
            onPick={!res && pickMode ? (x, y) => (pickMode === "location" ? setLocation([x, y]) : setCenter([x, y])) : undefined}
            pickHint={pickMode === "location" ? "Click to place the urgent order" : "Click to centre the affected area"}
            tooltip={(s) => stopTooltip(s, fmt, fmtDur, {
              profile: outcome?.stop_profiles.find((p) => p.node === s.index),
              note: completed.has(s.index) ? <div className="tt-row"><span>Status</span><b>completed before event</b></div> : undefined,
            })}
            caption={geo ? "Straight segments between consecutive stops, not road paths" : "Benchmark coordinate space"}
          />
        </div>
        <div className="canvas-legend">
          {res ? (
            <Legend items={[
              ...RISK_BANDS.map((b) => ({ label: b.label, color: b.color })),
              { label: "Reassigned stop", color: "#1f47d6", shape: "ring" as const },
              { label: "Completed", color: "#c9cdd4" },
              { label: "Spare vehicle", color: "#0b1324", shape: "line" as const },
            ]} />
          ) : (
            <span className="legend-note"><MapPin size={12} /> Configure an event, then inject it into the plan in operation.</span>
          )}
        </div>
      </section>

      <aside className="decision" aria-label="Replanning outcomes">
        <div className="eyebrow">Outcome</div>
        {run.status === "error" && <ErrorNote>{run.error}</ErrorNote>}
        {!res && run.status !== "error" && (
          <Empty icon={<Zap size={18} />} title={run.status === "running" ? "Replanning" : "Awaiting an event"}>
            {run.status === "running" ? run.message : "The engine observes each vehicle's progress at the event time, updates the routing problem and re-solves it under each policy."}
          </Empty>
        )}
        {res && <Outcomes res={res} shown={shown} setShown={setShown} fmtDur={fmtDur} fmtCost={fmtCost} />}
      </aside>
    </div>
  );
}

function Outcomes({ res, shown, setShown, fmtDur, fmtCost }: { res: DisruptionResult; shown: Policy; setShown: (p: Policy) => void; fmtDur: (d: number) => string; fmtCost: (c: number) => string }) {
  const pols = Object.keys(res.policies) as Policy[];
  const best = pols.reduce((a, b) => (res.policies[b]!.metrics.on_time_rate > res.policies[a]!.metrics.on_time_rate ? b : a), pols[0]);
  const o = res.policies[shown]!;
  return (
    <>
      <table className="cmp">
        <thead>
          <tr>
            <th />
            {pols.map((p) => (
              <th key={p} className="r" title={POLICY_LABEL[p]}><span className="swatch" style={{ background: POLICY_COLOR[p] }} />{POLICY_SHORT[p]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr className="strong"><th scope="row">On-time stops</th>{pols.map((p) => <td key={p} className="r num">{pct(res.policies[p]!.metrics.on_time_rate)}</td>)}</tr>
          <tr><th scope="row">Expected lateness</th>{pols.map((p) => <td key={p} className="r num">{fmtDur(res.policies[p]!.metrics.lateness_total_mean)}</td>)}</tr>
          <tr><th scope="row">Overtime risk</th>{pols.map((p) => <td key={p} className="r num">{pct(res.policies[p]!.metrics.p_overtime, 0)}</td>)}</tr>
          <tr><th scope="row">Travel cost</th>{pols.map((p) => <td key={p} className="r num">{fmtCost(res.policies[p]!.metrics.distance)}</td>)}</tr>
          <tr><th scope="row">Routes</th>{pols.map((p) => <td key={p} className="r num">{res.policies[p]!.metrics.n_routes}</td>)}</tr>
          <tr><th scope="row">Stops reassigned</th>{pols.map((p) => <td key={p} className="r num">{res.policies[p]!.diff.n_moved}</td>)}</tr>
          <tr><th scope="row">Unserved</th>{pols.map((p) => <td key={p} className="r num">{res.policies[p]!.unserved.length}</td>)}</tr>
          <tr><th scope="row">Replan time</th>{pols.map((p) => <td key={p} className="r num">{num(res.policies[p]!.runtime_s, 2)} s</td>)}</tr>
        </tbody>
      </table>
      <p className="cmp-foot">{res.metrics_scope}. Same {res.policies[pols[0]]!.metrics.n_scenarios} scenarios for every policy.</p>
      <div className="verdict ok" style={{ gap: 6 }}>
        <StatusPill tone="neutral">Highest on-time rate: {POLICY_LABEL[best]}</StatusPill>
        <p className="verdict-text">This ranking is for this single event and realised world (seed {res.world_seed}); the Evidence view aggregates many.</p>
      </div>
      <div className="frontier-block">
        <div className="block-head">
          <div className="eyebrow">What changed · {POLICY_LABEL[shown]}</div>
          <Segmented<Policy> size="sm" label="Policy" value={shown} onChange={setShown} options={pols.map((p) => ({ value: p, label: POLICY_LABEL[p].split(" ")[0] }))} />
        </div>
        <ul className="changes">
          {res.state.vehicles.filter((v) => v.status === "broken").map((v) => (
            <li key={`b${v.route_index}`}><span className="chg-tag bad">Out</span> Vehicle {v.route_index + 1} stopped with {v.remaining.length + (v.committed != null ? 1 : 0)} stops left</li>
          ))}
          {res.new_stop && <li><span className="chg-tag acc">New</span> Urgent stop{res.new_stop.estimated_travel ? " (travel times model-estimated)" : ""}</li>}
          <li><span className="chg-tag">{o.diff.n_moved}</span> stops reassigned between vehicles</li>
          <li><span className="chg-tag">{o.diff.resequenced_vehicles.length}</span> vehicles resequenced</li>
          {o.beta > 0 && <li><span className="chg-tag acc">β {o.beta.toFixed(2)}</span> safety buffer selected for the residual plan</li>}
          {o.diff.moved.slice(0, 8).map((m) => (
            <li key={m.stop} className="small muted">Stop {m.stop}: {lbl(m.from)} → {lbl(m.to)}</li>
          ))}
          {o.diff.moved.length > 8 && <li className="small muted">and {o.diff.moved.length - 8} more</li>}
        </ul>
      </div>
      <div className="prov-foot">
        <ProvTag kind="synthetic">Event: synthetic</ProvTag>
        <ProvTag kind="measured">Outcomes: simulated</ProvTag>
      </div>
    </>
  );
}

function lbl(v: number | null) {
  if (v == null) return "unassigned";
  if (v >= 1000) return `spare ${v - 999}`;
  return `vehicle ${v + 1}`;
}

function median(xs: number[]) {
  const s = [...xs].sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : 0;
}
