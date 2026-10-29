import { useMemo, useState } from "react";
import { scaleLinear } from "d3-scale";
import type { PlanRoute, Stop, StopProfile } from "../../api/types";
import { pct } from "../../lib/format";
import { riskColor } from "../../lib/risk";
import "./charts.css";

interface Props {
  routes: PlanRoute[];
  stops: Stop[];
  profiles: StopProfile[];
  horizon: [number, number];
  formatTime: (t: number) => string;
  vehicleColor: (i: number) => string;
  selected: number | null;
  onSelect: (i: number | null) => void;
}

/** One row per vehicle: each stop's delivery window (bar) against the
 * simulated arrival band P10–P90 (whisker) and median (dot, risk-coloured). */
export function ScheduleStrip({ routes, stops, profiles, horizon, formatTime, vehicleColor, selected, onSelect }: Props) {
  const [hover, setHover] = useState<{ node: number; x: number; y: number } | null>(null);
  const prof = useMemo(() => new Map(profiles.map((p) => [p.node, p])), [profiles]);
  // Dense routes (Amazon: ~100 stops per van) are staggered over sub-lanes by
  // sequence position so overlapping windows stay readable.
  const maxStops = Math.max(1, ...routes.map((r) => r.stops.length));
  const lanes = Math.min(6, Math.max(1, Math.ceil(maxStops / 14)));
  const laneH = lanes === 1 ? 22 : 9;
  const rowH = lanes === 1 ? 22 : lanes * laneH + 8;
  const W = 1000, m = { l: 44, r: 12, t: 22, b: 6 };
  const H = m.t + routes.length * rowH + m.b;
  const x = scaleLinear().domain(horizon).range([m.l, W - m.r]);
  const ticks = x.ticks(8);
  const hp = hover ? prof.get(hover.node) : undefined;
  const hs = hover ? stops[hover.node] : undefined;

  return (
    <div className="schedule" onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Vehicle schedules with delivery windows and simulated arrival bands">
        {ticks.map((t) => (
          <g key={t} className="gridline">
            <line x1={x(t)} x2={x(t)} y1={m.t - 4} y2={H} />
            <text x={x(t)} y={12} textAnchor="middle">{formatTime(t)}</text>
          </g>
        ))}
        {routes.map((r, i) => {
          const y0 = m.t + i * rowH;
          const dim = selected != null && selected !== i;
          return (
            <g key={i} opacity={dim ? 0.3 : 1} className="schedule-row" onClick={() => onSelect(selected === i ? null : i)}>
              <rect x={0} y={y0} width={W} height={rowH} fill={selected === i ? "var(--accent-tint)" : "transparent"} />
              <rect x={6} y={y0 + rowH / 2 - 5} width={10} height={10} rx={2} fill={vehicleColor(i)} />
              <text className="row-label" x={20} y={y0 + rowH / 2 + 4}>{i + 1}</text>
              <line x1={x(r.planned_start)} x2={x(r.planned_end)} y1={y0 + rowH / 2} y2={y0 + rowH / 2} stroke="var(--line-2)" strokeWidth={1} />
              {r.stops.map((n, k) => {
                const s = stops[n];
                const p = prof.get(n);
                if (!s || !p) return null;
                const cy = lanes === 1 ? y0 + rowH / 2 : y0 + 4 + (k % lanes) * laneH + laneH / 2;
                const barH = lanes === 1 ? 12 : 6;
                return (
                  <g
                    key={n}
                    onMouseEnter={(e) => {
                      const host = (e.currentTarget.ownerSVGElement!.parentElement as HTMLElement).getBoundingClientRect();
                      setHover({ node: n, x: e.clientX - host.left, y: e.clientY - host.top });
                    }}
                  >
                    {s.has_tw && (
                      <rect x={x(s.tw_early)} y={cy - barH / 2} width={Math.max(1, x(s.tw_late) - x(s.tw_early))} height={barH} rx={2} className="tw-bar" />
                    )}
                    <line x1={x(p.arrival_p10)} x2={x(p.arrival_p90)} y1={cy} y2={cy} stroke={riskColor(p.p_late)} strokeWidth={2} strokeLinecap="round" />
                    <circle cx={x(p.arrival_p50)} cy={cy} r={2.6} fill={riskColor(p.p_late)} />
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      {hover && hs && hp && (
        <div className="chart-tip floating" style={{ left: hover.x, top: hover.y }}>
          <b className="num">{hs.id}</b>
          {hs.has_tw && <span>Window {formatTime(hs.tw_early)}–{formatTime(hs.tw_late)}</span>}
          <span>Arrival P10–P90 {formatTime(hp.arrival_p10)}–{formatTime(hp.arrival_p90)}</span>
          <span>P(late) {pct(hp.p_late)}</span>
        </div>
      )}
    </div>
  );
}
