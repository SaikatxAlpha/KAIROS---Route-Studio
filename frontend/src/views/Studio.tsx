import { useMemo, useState } from "react";
import { Layers, MapPinned, Play, Route as RouteIcon, ShieldCheck } from "lucide-react";
import type { Method, Stop } from "../api/types";
import { RouteMap, type StopStyle } from "../components/map/RouteMap";
import { ScheduleStrip } from "../components/charts/ScheduleStrip";
import { Empty, ErrorNote, Legend, Progress, ProvTag, Segmented } from "../components/ui";
import { METHOD_SHORT, VEHICLE_COLORS, makeDurationFormat, makeTimeFormat } from "../lib/format";
import { RISK_BANDS } from "../lib/risk";
import { useStore } from "../state/store";
import { ScenarioRail } from "./studio/ScenarioRail";
import { DecisionPanel } from "./studio/DecisionPanel";
import { NEUTRAL_ROUTE, planToMapRoutes, riskStyle, stopTooltip, vehicleColorFn } from "./shared";
import "./studio.css";

type ColorMode = "risk" | "vehicle";

export function Studio() {
  const { instance, instanceError, compare, shownMethod, setShownMethod } = useStore();
  const [colorMode, setColorMode] = useState<ColorMode>("risk");
  const [selected, setSelected] = useState<number | null>(null);
  const summary = instance?.summary;
  const fmt = useMemo(() => makeTimeFormat(summary), [summary]);
  const fmtDur = useMemo(() => makeDurationFormat(summary), [summary]);
  const result = compare.result;
  const plan = result?.plans[shownMethod];
  const methods = result ? (Object.keys(result.plans) as Method[]) : [];

  const profiles = useMemo(() => new Map((plan?.stop_profiles ?? []).map((p) => [p.node, p])), [plan]);
  const vehicleOf = useMemo(() => {
    const m = new Map<number, number>();
    plan?.routes.forEach((r, i) => r.stops.forEach((s) => m.set(s, i)));
    return m;
  }, [plan]);

  const histColors = summary?.source === "amazon";
  const routes = useMemo(() => {
    if (plan) return planToMapRoutes(plan, selected);
    return [];
  }, [plan, selected]);

  const styleFor = useMemo(() => {
    if (!plan) {
      return (s: Stop): StopStyle =>
        histColors && s.historical_route != null && s.historical_route >= 0
          ? { fill: VEHICLE_COLORS[s.historical_route % VEHICLE_COLORS.length], r: 3.8 }
          : { fill: "#5f6878", r: 3.8 };
    }
    if (colorMode === "risk") {
      const dim = selected == null ? undefined : new Set([...vehicleOf.entries()].filter(([, v]) => v !== selected).map(([k]) => k));
      return riskStyle(profiles, dim);
    }
    const color = vehicleColorFn(plan.routes.length, selected);
    return (s: Stop): StopStyle => {
      const v = vehicleOf.get(s.index);
      return v == null ? { fill: "#c3c7cf", r: 3.5 } : { fill: color(v), r: 4.2, opacity: selected == null || selected === v ? 1 : 0.3 };
    };
  }, [plan, colorMode, profiles, vehicleOf, selected, histColors]);

  const nRoutes = plan?.routes.length ?? 0;
  const caption = summary?.coord_system === "wgs84"
    ? "Published stop coordinates · straight segments between consecutive stops, not road paths"
    : "Abstract benchmark coordinate space (Euclidean), not a geographic map";

  return (
    <div className="studio">
      <ScenarioRail />
      <section className="studio-main" aria-label="Route canvas">
        {instanceError && <ErrorNote>{instanceError}</ErrorNote>}
        {!instance && !instanceError && <div className="canvas-loading"><Progress value={0.3} message="Loading instance" /></div>}
        {instance && summary && (
          <>
            <header className="canvas-head">
              <div className="canvas-title">
                <div className="eyebrow">{summary.source === "amazon" ? `Amazon Last Mile · ${summary.meta.city}` : summary.source === "solomon" ? `Solomon benchmark · ${summary.meta.group}` : "Synthetic"}</div>
                <h1>{summary.name}</h1>
              </div>
              <div className="canvas-tags">
                <ProvTag kind="observed" title={(instance.provenance.observed ?? []).join("; ")}>
                  {summary.source === "synthetic" ? "No observed data" : "Observed benchmark"}
                </ProvTag>
                {(instance.provenance.model_estimated?.length ?? 0) > 0 && (
                  <ProvTag kind="estimated" title={instance.provenance.model_estimated!.join("; ")}>
                    {Math.round((1 - summary.share_tt_observed) * 100)}% arcs model-estimated
                  </ProvTag>
                )}
                <ProvTag kind="synthetic" title={(instance.provenance.synthetic ?? []).join("; ")}>Synthetic variability</ProvTag>
              </div>
            </header>

            <div className="canvas-toolbar">
              {result ? (
                <Segmented
                  label="Plan shown"
                  value={shownMethod}
                  onChange={(m) => { setShownMethod(m); setSelected(null); }}
                  options={methods.map((m) => ({ value: m, label: METHOD_SHORT[m] }))}
                />
              ) : (
                <span className="toolbar-note"><MapPinned size={14} /> {summary.n_clients} stops · {summary.num_vehicles} vehicles available</span>
              )}
              <div className="toolbar-right">
                {plan && (
                  <Segmented
                    size="sm"
                    label="Colour stops by"
                    value={colorMode}
                    onChange={setColorMode}
                    options={[
                      { value: "risk", label: <><ShieldCheck size={12} /> Risk</> },
                      { value: "vehicle", label: <><Layers size={12} /> Vehicle</> },
                    ]}
                  />
                )}
              </div>
            </div>

            <div className="canvas-map">
              <RouteMap
                coordSystem={summary.coord_system}
                stops={instance.stops}
                routes={routes}
                styleFor={styleFor}
                tooltip={(s) => stopTooltip(s, fmt, fmtDur, { vehicle: vehicleOf.get(s.index), profile: profiles.get(s.index) })}
                caption={caption}
              />
              {!plan && compare.status !== "running" && (
                <div className="canvas-overlay-hint">
                  <Play size={14} /> Run the comparison to solve and evaluate plans
                </div>
              )}
            </div>

            <div className="canvas-legend">
              {plan && colorMode === "risk" && (
                <Legend items={RISK_BANDS.map((b) => ({ label: b.label, color: b.color }))} />
              )}
              {plan && colorMode === "vehicle" && nRoutes > VEHICLE_COLORS.length && (
                <Legend items={[{ label: `${nRoutes} routes (select a row below to highlight)`, color: NEUTRAL_ROUTE, shape: "line" }]} />
              )}
              {plan && colorMode === "vehicle" && nRoutes <= VEHICLE_COLORS.length && (
                <Legend items={plan.routes.map((_, i) => ({ label: `Vehicle ${i + 1}`, color: VEHICLE_COLORS[i], shape: "line" }))} />
              )}
              {!plan && histColors && (
                <Legend items={(summary.meta.route_ids as string[]).map((_, i) => ({ label: `Historical route ${i + 1}`, color: VEHICLE_COLORS[i] }))} />
              )}
              {plan && <span className="legend-note"><RouteIcon size={12} /> Risk = simulated probability of arriving after the window closes</span>}
            </div>

            {plan && (
              <div className="schedule-panel">
                <div className="schedule-head">
                  <div>
                    <div className="eyebrow">Schedule · {METHOD_SHORT[shownMethod]}</div>
                    <div className="schedule-sub">Bars: delivery windows · whiskers: simulated arrival P10–P90 · click a row to isolate a vehicle</div>
                  </div>
                </div>
                <div className="schedule-scroll">
                  <ScheduleStrip
                    routes={plan.routes}
                    stops={instance.stops}
                    profiles={plan.stop_profiles}
                    horizon={[summary.meta?.t0_utc_s != null ? 0 : instance.stops[0].tw_early, summary.horizon]}
                    formatTime={fmt}
                    vehicleColor={vehicleColorFn(plan.routes.length, selected)}
                    selected={selected}
                    onSelect={setSelected}
                  />
                </div>
              </div>
            )}
            {!plan && compare.status === "idle" && (
              <div className="schedule-panel">
                <Empty title="No plan yet">Schedules, arrival-time bands and per-stop risk appear after the planners run.</Empty>
              </div>
            )}
          </>
        )}
      </section>
      <DecisionPanel />
    </div>
  );
}
