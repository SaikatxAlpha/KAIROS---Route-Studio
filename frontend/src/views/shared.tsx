import type { ReactNode } from "react";
import type { InstanceDetail, PlanResult, Stop, StopProfile } from "../api/types";
import type { MapRoute, StopStyle } from "../components/map/RouteMap";
import { VEHICLE_COLORS, pct } from "../lib/format";
import { riskColor } from "../lib/risk";

export const NEUTRAL_ROUTE = "#8b93a3";

export function vehicleColorFn(nRoutes: number, selected: number | null) {
  return (i: number) => {
    if (nRoutes <= VEHICLE_COLORS.length) return VEHICLE_COLORS[i];
    return selected === i ? "#1f47d6" : NEUTRAL_ROUTE;
  };
}

export function planToMapRoutes(plan: PlanResult, selected: number | null): MapRoute[] {
  const color = vehicleColorFn(plan.routes.length, selected);
  return plan.routes.map((r, i) => ({
    key: `r${i}`,
    nodes: [0, ...r.stops, 0],
    color: color(i),
    emphasis: selected == null ? "normal" : selected === i ? "highlight" : "dim",
  }));
}

export function stopTooltip(
  s: Stop,
  fmt: (t: number) => string,
  fmtDur: (d: number) => string,
  extra?: { vehicle?: number; profile?: StopProfile; note?: ReactNode },
) {
  return (
    <div>
      <div className="tt-head">
        <span className="tt-id">{s.is_depot ? "Depot" : s.id}</span>
        {s.zone && <span className="muted" style={{ fontSize: 11 }}>zone {s.zone}</span>}
      </div>
      {!s.is_depot && s.has_tw && (
        <div className="tt-row">
          <span>Window{s.tw_source === "synthetic" ? " (synthetic)" : s.tw_source === "observed" ? " (observed)" : ""}</span>
          <b>{fmt(s.tw_early)}–{fmt(s.tw_late)}</b>
        </div>
      )}
      {s.is_depot && (
        <div className="tt-row"><span>Shift</span><b>{fmt(s.tw_early)}–{fmt(s.tw_late)}</b></div>
      )}
      {!s.is_depot && <div className="tt-row"><span>Planned service</span><b>{fmtDur(s.service)}</b></div>}
      {extra?.vehicle != null && <div className="tt-row"><span>Vehicle</span><b>{extra.vehicle + 1}</b></div>}
      {extra?.profile && (
        <>
          <div className="tt-row"><span>Arrival P10–P90</span><b>{fmt(extra.profile.arrival_p10)}–{fmt(extra.profile.arrival_p90)}</b></div>
          <div className="tt-row"><span>P(late)</span><b style={{ color: riskColor(extra.profile.p_late) }}>{pct(extra.profile.p_late)}</b></div>
        </>
      )}
      {extra?.note}
    </div>
  );
}

export function riskStyle(profiles: Map<number, StopProfile>, dimNodes?: Set<number>) {
  return (s: Stop): StopStyle => {
    const p = profiles.get(s.index);
    if (!p) return { fill: "#c3c7cf", r: 3.5 };
    return { fill: riskColor(p.p_late), r: 4.5, opacity: dimNodes?.has(s.index) ? 0.35 : 1 };
  };
}

export function provenanceKinds(inst: InstanceDetail) {
  const p = inst.provenance;
  return {
    observed: p.observed ?? [],
    estimated: [...(p.derived ?? []), ...(p.model_estimated ?? [])],
    synthetic: p.synthetic ?? [],
  };
}
