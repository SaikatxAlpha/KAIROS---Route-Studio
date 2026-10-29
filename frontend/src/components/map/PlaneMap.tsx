import { useMemo, useRef } from "react";
import type { RendererProps } from "./RouteMap";

/** Benchmark-space (Euclidean) renderer: honest abstract coordinates, no basemap. */
export function PlaneMap({ stops, routes, styleFor, onHover, onPick, overlay, extraStops }: RendererProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const all = useMemo(() => [...stops, ...(extraStops ?? [])], [stops, extraStops]);
  const W = 1000;
  const H = 720;
  const pad = 36;
  const { sx, sy, inv, ticksX, ticksY } = useMemo(() => {
    const xs = all.map((s) => s.x);
    const ys = all.map((s) => s.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const span = Math.max(maxX - minX, maxY - minY, 1);
    const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
    const k = Math.min((W - 2 * pad) / (maxX - minX || span), (H - 2 * pad) / (maxY - minY || span));
    // visible extent in data coordinates
    const x0 = cx - W / 2 / k, x1 = cx + W / 2 / k, y0 = cy - H / 2 / k, y1 = cy + H / 2 / k;
    const sx = (x: number) => W / 2 + (x - cx) * k;
    const sy = (y: number) => H / 2 - (y - cy) * k;
    const inv = (px: number, py: number) => [cx + (px - W / 2) / k, cy - (py - H / 2) / k] as const;
    const step = niceStep(span / 6);
    const ticks = (a: number, b: number) => {
      const out: number[] = [];
      for (let v = Math.ceil(a / step) * step; v <= b; v += step) out.push(v);
      return out;
    };
    return { sx, sy, inv, ticksX: ticks(x0, x1), ticksY: ticks(y0, y1) };
  }, [all]);

  const toSvgPoint = (e: React.MouseEvent) => {
    const svg = svgRef.current!;
    const rect = svg.getBoundingClientRect();
    const scale = Math.min(rect.width / W, rect.height / H);
    const offX = (rect.width - W * scale) / 2;
    const offY = (rect.height - H * scale) / 2;
    return [(e.clientX - rect.left - offX) / scale, (e.clientY - rect.top - offY) / scale] as const;
  };

  const byIndex = new Map(all.map((s) => [s.index, s]));
  const ordered = [...routes].sort((a, b) => rank(a.emphasis) - rank(b.emphasis));

  return (
    <svg
      ref={svgRef}
      className="planemap"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="xMidYMid meet"
      onClick={(e) => {
        if (!onPick) return;
        const [px, py] = toSvgPoint(e);
        const [x, y] = inv(px, py);
        onPick(x, y);
      }}
      onMouseLeave={() => onHover(null)}
      role="img"
      aria-label="Route plan in benchmark coordinate space"
    >
      <g className="grid">
        {ticksX.map((t) => (
          <g key={`x${t}`}>
            <line x1={sx(t)} x2={sx(t)} y1={0} y2={H} />
            <text x={sx(t) + 4} y={H - 6}>{t}</text>
          </g>
        ))}
        {ticksY.map((t) => (
          <g key={`y${t}`}>
            <line y1={sy(t)} y2={sy(t)} x1={0} x2={W} />
            <text x={4} y={sy(t) - 4}>{t}</text>
          </g>
        ))}
      </g>
      {overlay?.circle && (
        <circle
          className="area"
          cx={sx(overlay.circle.x)}
          cy={sy(overlay.circle.y)}
          r={overlay.circle.radius * Math.abs(sx(1) - sx(0))}
        />
      )}
      <g>
        {ordered.map((r) => {
          const pts = r.nodes.map((n) => byIndex.get(n)).filter(Boolean).map((s) => `${sx(s!.x)},${sy(s!.y)}`);
          return (
            <polyline
              key={r.key}
              points={pts.join(" ")}
              fill="none"
              stroke={r.color}
              strokeWidth={r.emphasis === "highlight" ? 3 : 2}
              strokeOpacity={r.emphasis === "dim" ? 0.22 : 0.9}
              strokeDasharray={r.dashed ? "6 5" : undefined}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          );
        })}
      </g>
      <g>
        {all.map((s) => {
          const st = styleFor(s);
          const cx = sx(s.x), cy = sy(s.y);
          if (s.is_depot) {
            return (
              <g key={s.index} onMouseEnter={(e) => onHover(s, ...rel(e, svgRef.current!))}>
                <rect x={cx - 8} y={cy - 8} width={16} height={16} rx={3} fill="var(--ink)" stroke="#fff" strokeWidth={2} />
              </g>
            );
          }
          return (
            <g
              key={s.index}
              onMouseEnter={(e) => onHover(s, ...rel(e, svgRef.current!))}
              onMouseLeave={() => onHover(null)}
            >
              <circle cx={cx} cy={cy} r={12} fill="transparent" />
              {st.ring && <circle cx={cx} cy={cy} r={(st.r ?? 5) + 4} fill="none" stroke={st.ring} strokeWidth={2} />}
              <circle cx={cx} cy={cy} r={st.r ?? 5} fill={st.fill} stroke={st.stroke ?? "#fff"} strokeWidth={1.5} opacity={st.opacity ?? 1} />
            </g>
          );
        })}
      </g>
      {overlay?.marker && (
        <g transform={`translate(${sx(overlay.marker.x)},${sy(overlay.marker.y)})`}>
          <rect x={-7} y={-7} width={14} height={14} transform="rotate(45)" fill="var(--accent)" stroke="#fff" strokeWidth={2} />
        </g>
      )}
    </svg>
  );
}

function rank(e?: string) {
  return e === "dim" ? 0 : e === "highlight" ? 2 : 1;
}

function rel(e: React.MouseEvent, svg: SVGSVGElement): [number, number] {
  const host = svg.parentElement!.getBoundingClientRect();
  return [e.clientX - host.left, e.clientY - host.top];
}

function niceStep(raw: number) {
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}
