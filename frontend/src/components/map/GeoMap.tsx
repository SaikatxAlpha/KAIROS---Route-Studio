import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { RendererProps } from "./RouteMap";

/** WGS84 renderer: Leaflet + OpenStreetMap basemap (greyscale). Route lines are straight
 * segments between consecutive stops (the dataset has no road geometry). */
export function GeoMap({ stops, routes, styleFor, onHover, onPick, overlay, extraStops }: RendererProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const fittedRef = useRef<string>("");
  const pickRef = useRef(onPick);
  pickRef.current = onPick;
  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;

  useEffect(() => {
    if (!hostRef.current || mapRef.current) return;
    const map = L.map(hostRef.current, {
      preferCanvas: true,
      zoomControl: true,
      attributionControl: true,
      scrollWheelZoom: true,
    });
    // OpenStreetMap standard tiles (no key). Rendered in quiet greyscale via CSS.
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(map);
    map.on("click", (e: L.LeafletMouseEvent) => pickRef.current?.(e.latlng.lng, e.latlng.lat));
    layerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(hostRef.current);
    return () => {
      ro.disconnect();
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
      fittedRef.current = "";
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();
    const all = [...stops, ...(extraStops ?? [])];
    const byIndex = new Map(all.map((s) => [s.index, s]));
    const key = stops.map((s) => s.id).join("|").slice(0, 2000) + stops.length;
    if (fittedRef.current !== key && stops.length) {
      // Fit the delivery area; the station can sit far outside it (zoom out to see it).
      const drop = stops.filter((s) => !s.is_depot);
      map.fitBounds(L.latLngBounds((drop.length ? drop : stops).map((s) => [s.y, s.x] as [number, number])), { padding: [28, 28] });
      fittedRef.current = key;
    }
    if (overlay?.circle) {
      L.circle([overlay.circle.y, overlay.circle.x], {
        radius: overlay.circle.radius * 1000,
        color: "#1f47d6",
        weight: 1.5,
        dashArray: "5 5",
        fillColor: "#1f47d6",
        fillOpacity: 0.06,
        interactive: false,
      }).addTo(layer);
    }
    const ordered = [...routes].sort((a, b) => rank(a.emphasis) - rank(b.emphasis));
    for (const r of ordered) {
      const pts = r.nodes.map((n) => byIndex.get(n)).filter(Boolean).map((s) => [s!.y, s!.x] as [number, number]);
      L.polyline(pts, {
        color: r.color,
        weight: r.emphasis === "highlight" ? 3.5 : 2.2,
        opacity: r.emphasis === "dim" ? 0.2 : 0.88,
        dashArray: r.dashed ? "6 6" : undefined,
        interactive: false,
        lineJoin: "round",
      }).addTo(layer);
    }
    for (const s of all) {
      const st = styleFor(s);
      const ll: [number, number] = [s.y, s.x];
      if (s.is_depot) {
        const m = L.marker(ll, {
          icon: L.divIcon({ className: "depot-icon", html: "<span></span>", iconSize: [18, 18] }),
          keyboard: false,
        }).addTo(layer);
        bindHover(m, s);
        continue;
      }
      if (st.ring) {
        L.circleMarker(ll, { radius: (st.r ?? 4.5) + 4, color: st.ring, weight: 2, fill: false, interactive: false }).addTo(layer);
      }
      const c = L.circleMarker(ll, {
        radius: st.r ?? 4.5,
        color: st.stroke ?? "#ffffff",
        weight: 1.2,
        fillColor: st.fill,
        fillOpacity: st.opacity ?? 1,
        opacity: 1,
      }).addTo(layer);
      bindHover(c, s);
    }
    if (overlay?.marker) {
      L.marker([overlay.marker.y, overlay.marker.x], {
        icon: L.divIcon({ className: "urgent-icon", html: "<span></span>", iconSize: [18, 18] }),
        interactive: false,
      }).addTo(layer);
    }

    function bindHover(m: L.Layer & { on: L.Evented["on"] }, s: (typeof all)[number]) {
      m.on("mouseover", (e: L.LeafletMouseEvent) => {
        const p = map!.latLngToContainerPoint(e.latlng);
        hoverRef.current(s, p.x, p.y);
      });
      m.on("mouseout", () => hoverRef.current(null));
    }
  }, [stops, routes, styleFor, overlay, extraStops]);

  return <div ref={hostRef} className="geomap" aria-label="Route plan on map" role="application" />;
}

function rank(e?: string) {
  return e === "dim" ? 0 : e === "highlight" ? 2 : 1;
}
