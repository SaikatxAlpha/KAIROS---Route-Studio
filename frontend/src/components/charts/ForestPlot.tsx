import { useState } from "react";
import { scaleLinear } from "d3-scale";
import "./charts.css";

export interface ForestRow {
  group: string;
  label: string;
  color: string;
  mean: number;
  ci: [number, number];
  n?: number;
  p?: number | null;
}

/** Paired effects with 95% CIs, grouped rows, zero reference line. */
export function ForestPlot({ rows, unit, title, height }: { rows: ForestRow[]; unit: string; title: string; height?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const rowH = 18;
  const groups = [...new Set(rows.map((r) => r.group))];
  const lines: ({ kind: "g"; label: string } | { kind: "r"; row: ForestRow; i: number })[] = [];
  groups.forEach((g) => {
    lines.push({ kind: "g", label: g });
    rows.forEach((r, i) => r.group === g && lines.push({ kind: "r", row: r, i }));
  });
  const W = 520, m = { l: 92, r: 16, t: 8, b: 26 };
  const H = height ?? m.t + lines.length * rowH + m.b;
  const lo = Math.min(0, ...rows.map((r) => r.ci[0]));
  const hi = Math.max(0, ...rows.map((r) => r.ci[1]));
  const x = scaleLinear().domain([lo - (hi - lo) * 0.05, hi + (hi - lo) * 0.05]).range([m.l, W - m.r]).nice(5);
  const h = hover != null ? rows[hover] : null;
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
        {x.ticks(5).map((t) => (
          <g key={t} className="gridline">
            <line x1={x(t)} x2={x(t)} y1={m.t} y2={H - m.b} />
            <text x={x(t)} y={H - m.b + 14} textAnchor="middle">{t > 0 ? `+${t}` : t}{unit}</text>
          </g>
        ))}
        <line x1={x(0)} x2={x(0)} y1={m.t} y2={H - m.b} stroke="var(--ink)" strokeWidth={1} />
        {lines.map((ln, k) => {
          const y = m.t + k * rowH + rowH / 2;
          if (ln.kind === "g") {
            return <text key={`g${k}`} x={4} y={y + 4} className="forest-group">{ln.label}</text>;
          }
          const r = ln.row;
          return (
            <g key={`r${k}`} onMouseEnter={() => setHover(ln.i)} onMouseLeave={() => setHover(null)}>
              <rect x={0} y={y - rowH / 2} width={W} height={rowH} fill={hover === ln.i ? "var(--surface-2)" : "transparent"} />
              <text x={16} y={y + 3.5} className="forest-label">{r.label}</text>
              <line x1={x(r.ci[0])} x2={x(r.ci[1])} y1={y} y2={y} stroke={r.color} strokeWidth={2} strokeLinecap="round" />
              <circle cx={x(r.mean)} cy={y} r={4} fill={r.color} stroke="#fff" strokeWidth={1.5} />
            </g>
          );
        })}
      </svg>
      {h && (
        <div className="chart-tip">
          <b>{h.group} · {h.label}</b>
          <span>Mean {h.mean > 0 ? "+" : ""}{h.mean.toFixed(2)}{unit}</span>
          <span>95% CI [{h.ci[0].toFixed(2)}, {h.ci[1].toFixed(2)}]</span>
          {h.n != null && <span>{h.n} paired instances</span>}
          {h.p != null && <span>Wilcoxon p = {h.p < 0.001 ? "<0.001" : h.p.toFixed(3)}</span>}
        </div>
      )}
    </div>
  );
}
