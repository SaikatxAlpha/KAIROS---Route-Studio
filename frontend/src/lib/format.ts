import type { InstanceSummary, Method, Policy } from "../api/types";

export const METHOD_LABEL: Record<Method, string> = {
  deterministic: "Deterministic baseline",
  buffered: "Quantile buffer",
  saa_select: "Scenario selection",
  reliability: "KAIROS reliability",
};

export const METHOD_SHORT: Record<Method, string> = {
  deterministic: "Baseline",
  buffered: "Buffer",
  saa_select: "Selection",
  reliability: "KAIROS",
};

export const METHOD_COLOR: Record<Method, string> = {
  deterministic: "#eb6834",
  buffered: "#1baf7a",
  saa_select: "#e87ba4",
  reliability: "#1f47d6",
};

export const POLICY_LABEL: Record<Policy, string> = {
  hold: "Hold + insert",
  reoptimise: "Re-optimise",
  reliability: "KAIROS replan",
};

export const POLICY_SHORT: Record<Policy, string> = {
  hold: "Hold",
  reoptimise: "Re-opt",
  reliability: "KAIROS",
};

export const POLICY_COLOR: Record<Policy, string> = {
  hold: "#eb6834",
  reoptimise: "#1baf7a",
  reliability: "#1f47d6",
};

export const VEHICLE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];

export function pct(x: number | null | undefined, digits = 1): string {
  if (x == null || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export function signedPct(x: number | null | undefined, digits = 1): string {
  if (x == null || Number.isNaN(x)) return "—";
  const v = x * 100;
  return `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(digits)}`;
}

export function num(x: number | null | undefined, digits = 0): string {
  if (x == null || Number.isNaN(x)) return "—";
  return x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function signed(x: number, digits = 0): string {
  const s = Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${x > 0 ? "+" : x < 0 ? "−" : "±"}${s}`;
}

/** Time formatting aware of the instance's units. Amazon times are seconds
 * after the earliest departure; shown as local clock time. */
export function makeTimeFormat(s: InstanceSummary | undefined) {
  if (!s) return (t: number) => num(t);
  if (s.time_unit === "s" && s.meta?.t0_utc_s != null) {
    const t0 = s.meta.t0_utc_s as number;
    const off = (s.meta.utc_offset_h as number) ?? 0;
    return (t: number) => {
      const secs = (((t0 + t + off * 3600) % 86400) + 86400) % 86400;
      const h = Math.floor(secs / 3600);
      const m = Math.floor((secs % 3600) / 60);
      return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
    };
  }
  return (t: number) => `t ${num(t)}`;
}

/** Duration formatting (for lateness, travel). */
export function makeDurationFormat(s: InstanceSummary | undefined) {
  if (s?.time_unit === "s") {
    return (d: number) => {
      if (d < 90) return `${num(d)} s`;
      if (d < 5400) return `${num(d / 60, 1)} min`;
      return `${num(d / 3600, 2)} h`;
    };
  }
  const unit = s?.time_unit === "min" ? " min" : " u";
  return (d: number) => `${num(d, d < 10 ? 1 : 0)}${unit}`;
}

export function costUnit(s: InstanceSummary | undefined): string {
  if (!s) return "";
  return s.distance_unit === "s" ? "drive-h" : "units";
}

/** Travel cost display: Amazon cost is driving time in seconds -> hours. */
export function makeCostFormat(s: InstanceSummary | undefined) {
  if (s?.distance_unit === "s") return (c: number) => `${num(c / 3600, 1)} h`;
  return (c: number) => num(c, 0);
}
