import { useState, type ReactNode } from "react";
import type { Stop } from "../../api/types";
import { GeoMap } from "./GeoMap";
import { PlaneMap } from "./PlaneMap";
import "./map.css";

export interface MapRoute {
  key: string;
  nodes: number[]; // node indices including start and end
  color: string;
  emphasis?: "normal" | "dim" | "highlight";
  dashed?: boolean;
}

export interface StopStyle {
  fill: string;
  stroke?: string;
  r?: number;
  ring?: string; // outer ring colour for "changed" markers
  opacity?: number;
}

export interface MapOverlay {
  circle?: { x: number; y: number; radius: number }; // radius: km (wgs84) or units (plane)
  marker?: { x: number; y: number; label: string };
}

export interface RouteMapProps {
  coordSystem: "euclidean" | "wgs84";
  stops: Stop[];
  routes: MapRoute[];
  styleFor: (s: Stop) => StopStyle;
  tooltip?: (s: Stop) => ReactNode;
  onPick?: (x: number, y: number) => void;
  pickHint?: string;
  overlay?: MapOverlay;
  extraStops?: Stop[];
  caption?: ReactNode;
}

export function RouteMap(props: RouteMapProps) {
  const [hover, setHover] = useState<{ stop: Stop; x: number; y: number } | null>(null);
  const onHover = (stop: Stop | null, x = 0, y = 0) => setHover(stop ? { stop, x, y } : null);
  const Renderer = props.coordSystem === "wgs84" ? GeoMap : PlaneMap;
  return (
    <div className={`routemap ${props.onPick ? "picking" : ""}`}>
      <Renderer {...props} onHover={onHover} />
      {props.pickHint && props.onPick && <div className="map-pick-hint">{props.pickHint}</div>}
      {hover && props.tooltip && (
        <div
          className="map-tooltip"
          style={{ left: hover.x, top: hover.y }}
          role="tooltip"
        >
          {props.tooltip(hover.stop)}
        </div>
      )}
      {props.caption && <div className="map-caption">{props.caption}</div>}
    </div>
  );
}

export type RendererProps = RouteMapProps & {
  onHover: (s: Stop | null, x?: number, y?: number) => void;
};
