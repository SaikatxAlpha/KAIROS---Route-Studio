// Status colours for per-stop lateness risk. Always shown with a legend/label.
export const RISK_BANDS = [
  { max: 0.05, color: "#13804c", label: "P(late) < 5%" },
  { max: 0.2, color: "#a8670a", label: "5–20%" },
  { max: 1.01, color: "#c0362b", label: "> 20%" },
];

export function riskColor(p: number): string {
  for (const b of RISK_BANDS) if (p < b.max) return b.color;
  return RISK_BANDS[RISK_BANDS.length - 1].color;
}
