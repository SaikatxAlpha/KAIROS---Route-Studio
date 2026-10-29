import { useState } from "react";
import { scaleLinear } from "d3-scale";
import "./charts.css";

export interface Series {
  label: string;
  color: string;
  points: { x: number; y: number; note?: string }[];
  dashed?: boolean;
}

/** Small multi-series line chart with direct labels and per-point hover. */
export function LineChart({
  series,
  xFormat,
  yFormat,
  xDomain,
  yDomain,
  diagonal,
  title,
  xLabel,
  yLabel,
}: {
  series: Series[];
  xFormat: (v: number) => string;
  yFormat: (v: number) => string;
  xDomain?: [number, number];
  yDomain?: [number, number];
  diagonal?: boolean;
  title: string;
  xLabel?: string;
  yLabel?: string;
}) {
  const [hover, setHover] = useState<{ s: number; p: number } | null>(null);
  const W = 420, H = 240, m = { l: 46, r: 84, t: 12, b: 38 };
  const xs = series.flatMap((s) => s.points.map((p) => p.x));
  const ys = series.flatMap((s) => s.points.map((p) => p.y));
  const x = scaleLinear().domain(xDomain ?? [Math.min(...xs), Math.max(...xs)]).range([m.l, W - m.r]);
  const yd = yDomain ?? padDomain(Math.min(...ys), Math.max(...ys));
  const y = scaleLinear().domain(yd).range([H - m.b, m.t]).nice(5);
  const hp = hover ? series[hover.s].points[hover.p] : null;
  // End-of-line labels, nudged apart vertically so they never collide.
  const labels = series
    .map((s, i) => ({ i, y: s.points.length ? y(s.points[s.points.length - 1].y) + 3 : 0 }))
    .sort((a, b) => a.y - b.y);
  for (let k = 1; k < labels.length; k++) labels[k].y = Math.max(labels[k].y, labels[k - 1].y + 13);
  const labelY = new Map(labels.map((l) => [l.i, l.y]));
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
        {y.ticks(5).map((t) => (
          <g key={t} className="gridline">
            <line x1={m.l} x2={W - m.r} y1={y(t)} y2={y(t)} />
            <text x={m.l - 6} y={y(t) + 3} textAnchor="end">{yFormat(t)}</text>
          </g>
        ))}
        {x.ticks(5).map((t) => (
          <text key={t} className="axis-text" x={x(t)} y={H - m.b + 15} textAnchor="middle">{xFormat(t)}</text>
        ))}
        {xLabel && <text className="axis-text" x={(m.l + W - m.r) / 2} y={H - 4} textAnchor="middle">{xLabel}</text>}
        {yLabel && <text className="axis-text" x={10} y={m.t - 2}>{yLabel}</text>}
        {diagonal && (
          <line x1={x(Math.max(x.domain()[0], y.domain()[0]))} y1={y(Math.max(x.domain()[0], y.domain()[0]))}
            x2={x(Math.min(x.domain()[1], y.domain()[1]))} y2={y(Math.min(x.domain()[1], y.domain()[1]))}
            stroke="var(--ink)" strokeDasharray="4 4" strokeWidth={1} />
        )}
        {series.map((s, si) => (
          <g key={s.label}>
            <polyline fill="none" stroke={s.color} strokeWidth={2} strokeDasharray={s.dashed ? "5 4" : undefined}
              points={s.points.map((p) => `${x(p.x)},${y(p.y)}`).join(" ")} />
            {s.points.map((p, pi) => (
              <g key={pi} onMouseEnter={() => setHover({ s: si, p: pi })} onMouseLeave={() => setHover(null)}>
                <circle cx={x(p.x)} cy={y(p.y)} r={10} fill="transparent" />
                <circle cx={x(p.x)} cy={y(p.y)} r={4} fill={s.color} stroke="#fff" strokeWidth={1.5} />
              </g>
            ))}
            {s.points.length > 0 && (
              <text x={x(s.points[s.points.length - 1].x) + 8} y={labelY.get(si)} className="series-label">{s.label}</text>
            )}
          </g>
        ))}
      </svg>
      {hp && hover && (
        <div className="chart-tip">
          <b>{series[hover.s].label}</b>
          <span>{xFormat(hp.x)} → {yFormat(hp.y)}</span>
          {hp.note && <span>{hp.note}</span>}
        </div>
      )}
    </div>
  );
}

function padDomain(a: number, b: number): [number, number] {
  const d = b - a || Math.abs(a) * 0.1 || 1;
  return [a - d * 0.1, b + d * 0.1];
}
