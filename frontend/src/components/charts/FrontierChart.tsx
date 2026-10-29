import { useMemo, useState } from "react";
import { scaleLinear } from "d3-scale";
import type { Candidate } from "../../api/types";
import { pct } from "../../lib/format";
import "./charts.css";

interface Props {
  candidates: Candidate[];
  target: number;
  baseline?: { distance: number; onTime: number }; // deterministic plan, out-of-sample
  chosenOos?: { distance: number; onTime: number }; // chosen plan, out-of-sample
  formatCost: (c: number) => string;
}

/** Candidate ladder: travel cost vs in-sample on-time rate, with the target. */
export function FrontierChart({ candidates, target, baseline, chosenOos, formatCost }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 340, H = 200, m = { l: 40, r: 12, t: 12, b: 30 };
  const { x, y, xt, yt } = useMemo(() => {
    const xs = [...candidates.map((c) => c.distance), ...(baseline ? [baseline.distance] : []), ...(chosenOos ? [chosenOos.distance] : [])];
    const ys = [...candidates.map((c) => c.in_sample_on_time_rate), target, ...(baseline ? [baseline.onTime] : []), ...(chosenOos ? [chosenOos.onTime] : [])];
    const x = scaleLinear().domain(pad(Math.min(...xs), Math.max(...xs), 0.08)).range([m.l, W - m.r]).nice(4);
    const yd = pad(Math.min(...ys), Math.min(1, Math.max(...ys)), 0.1);
    const y = scaleLinear().domain([yd[0], Math.min(1, yd[1])]).range([H - m.b, m.t]);
    return { x, y, xt: x.ticks(4), yt: y.ticks(4).filter((t) => t <= 1) };
  }, [candidates, target, baseline, chosenOos, m.l, m.r, m.t, m.b]);
  const sorted = [...candidates].sort((a, b) => a.beta - b.beta);
  const h = hover != null ? sorted[hover] : null;

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Candidate plans: travel cost versus estimated on-time rate">
        {yt.map((t) => (
          <g key={t} className="gridline">
            <line x1={m.l} x2={W - m.r} y1={y(t)} y2={y(t)} />
            <text x={m.l - 6} y={y(t) + 3} textAnchor="end">{pct(t, 0)}</text>
          </g>
        ))}
        {xt.map((t) => (
          <text key={t} className="axis-text" x={x(t)} y={H - m.b + 16} textAnchor="middle">{formatCost(t)}</text>
        ))}
        <line className="target-line" x1={m.l} x2={W - m.r} y1={y(target)} y2={y(target)} />
        <text className="target-label" x={W - m.r} y={y(target) - 5} textAnchor="end">target {pct(target, 1)}</text>
        <polyline
          className="frontier-path"
          points={sorted.map((c) => `${x(c.distance)},${y(c.in_sample_on_time_rate)}`).join(" ")}
        />
        {baseline && (
          <g>
            <circle cx={x(baseline.distance)} cy={y(baseline.onTime)} r={5} fill="#eb6834" stroke="#fff" strokeWidth={2} />
          </g>
        )}
        {chosenOos && (
          <rect x={x(chosenOos.distance) - 4.5} y={y(chosenOos.onTime) - 4.5} width={9} height={9} fill="#fff" stroke="#1f47d6" strokeWidth={2} transform={`rotate(45 ${x(chosenOos.distance)} ${y(chosenOos.onTime)})`} />
        )}
        {sorted.map((c, i) => (
          <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <circle cx={x(c.distance)} cy={y(c.in_sample_on_time_rate)} r={12} fill="transparent" />
            <circle
              cx={x(c.distance)}
              cy={y(c.in_sample_on_time_rate)}
              r={c.chosen ? 6 : 4.5}
              fill={c.chosen ? "#1f47d6" : "#fff"}
              stroke="#1f47d6"
              strokeWidth={2}
            />
            {(c.chosen || hover === i) && (
              <text className="point-label" x={x(c.distance) + 8} y={y(c.in_sample_on_time_rate) + 12}>β {c.beta.toFixed(2)}</text>
            )}
          </g>
        ))}
      </svg>
      {h && (
        <div className="chart-tip">
          <b>Buffer β = {h.beta.toFixed(2)}</b>
          <span>Cost {formatCost(h.distance)} · {h.n_routes} routes</span>
          <span>In-sample on-time {pct(h.in_sample_on_time_rate)}</span>
          <span>{h.planned_feasible ? "Feasible under buffered times" : "Buffered windows not all met (time warp)"}</span>
        </div>
      )}
    </div>
  );
}

function pad(a: number, b: number, f: number): [number, number] {
  const d = (b - a) || Math.abs(a) * 0.1 || 1;
  return [a - d * f, b + d * f];
}
