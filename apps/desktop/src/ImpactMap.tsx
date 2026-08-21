import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const API = () =>
  `http://127.0.0.1:${(window as unknown as { __rtPort?: number }).__rtPort ?? 8765}`;

// Colours are the single source of truth for both the map and the legend.
const ATTR_COLOR: Record<string, string> = {
  DIRECTLY_AFFECTED: "#ef4444",     // red
  SECONDARILY_AFFECTED: "#f59e0b",  // amber
  UNCHANGED: "#6b7280",             // grey
};

interface EdgeImpact {
  edge_id: string;
  attribution: string;
  impact_class: string;
  travel_time_delta_pct: number | null;
  queue_delta_m: number | null;
}
interface CriticalJunction {
  junction_id: string;
  impact_score: number;
}
export interface Impact {
  edges: EdgeImpact[];
  critical_junctions: CriticalJunction[];
  summary: Record<string, number | null>;
}

/**
 * Deterministic impact map: reuses the existing MapLibre stack and the
 * /network/geojson roads+junctions, colouring each road by its attribution
 * (unchanged / directly / secondarily affected) and marking the critical
 * junctions. All values come from the scenario's persisted impact result —
 * nothing is computed in the browser.
 */
export function ImpactMap({ impact }: { impact: Impact }) {
  const mapRef = useRef<HTMLDivElement | null>(null);
  const mapObj = useRef<maplibregl.Map | null>(null);
  const geojsonCache = useRef<any>(null);

  // init once
  useEffect(() => {
    if (!mapRef.current || mapObj.current) return;
    const map = new maplibregl.Map({
      container: mapRef.current,
      style: {
        version: 8,
        sources: {
          "osm-raster": {
            type: "raster",
            tiles: [
              "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
              "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
              "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
            ],
            tileSize: 256,
            attribution:
              '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
          },
        },
        layers: [{ id: "osm-tiles", type: "raster", source: "osm-raster", minzoom: 0, maxzoom: 19 }],
      },
      center: [0, 0],
      zoom: 12,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapObj.current = map;

    const resize = new ResizeObserver(() => map.resize());
    if (mapRef.current) resize.observe(mapRef.current);
    return () => {
      resize.disconnect();
      map.remove();
      mapObj.current = null;
    };
  }, []);

  // paint whenever the impact changes
  useEffect(() => {
    const map = mapObj.current;
    if (!map || !impact) return;

    const apply = async () => {
      if (!geojsonCache.current) {
        try {
          geojsonCache.current = await (await fetch(`${API()}/network/geojson`)).json();
        } catch {
          return;
        }
      }
      const gj = geojsonCache.current;
      if (!gj?.roads?.features) return;

      // Join impact onto road features by edge_id.
      const byEdge: Record<string, EdgeImpact> = {};
      impact.edges.forEach((e) => (byEdge[e.edge_id] = e));
      const roads = {
        ...gj.roads,
        features: gj.roads.features.map((f: any) => {
          const e = byEdge[f.properties?.edge_id];
          return {
            ...f,
            properties: {
              ...f.properties,
              attribution: e?.attribution ?? "UNCHANGED",
              impact_class: e?.impact_class ?? "UNCHANGED",
              tt_pct: e?.travel_time_delta_pct ?? null,
              queue_delta: e?.queue_delta_m ?? null,
            },
          };
        }),
      };

      const critical = new Set(impact.critical_junctions.map((j) => j.junction_id));
      const juncFeatures = (gj.junctions?.features ?? []).filter((f: any) =>
        critical.has(f.properties?.junction_id),
      );
      const juncs = { type: "FeatureCollection", features: juncFeatures };

      const draw = () => {
        // roads
        if (map.getSource("impact-roads")) {
          (map.getSource("impact-roads") as maplibregl.GeoJSONSource).setData(roads);
        } else {
          map.addSource("impact-roads", { type: "geojson", data: roads });
          map.addLayer({
            id: "impact-roads-line",
            type: "line",
            source: "impact-roads",
            layout: { "line-cap": "round", "line-join": "round" },
            paint: {
              "line-color": [
                "match",
                ["get", "attribution"],
                "DIRECTLY_AFFECTED", ATTR_COLOR.DIRECTLY_AFFECTED,
                "SECONDARILY_AFFECTED", ATTR_COLOR.SECONDARILY_AFFECTED,
                ATTR_COLOR.UNCHANGED,
              ],
              "line-width": [
                "match",
                ["get", "impact_class"],
                "SEVERE", 6, "HIGH", 5, "MODERATE", 4, "LOW", 3,
                2,
              ],
              "line-opacity": 0.9,
            },
          });
        }
        // critical junctions
        if (map.getSource("impact-junctions")) {
          (map.getSource("impact-junctions") as maplibregl.GeoJSONSource).setData(juncs as any);
        } else {
          map.addSource("impact-junctions", { type: "geojson", data: juncs as any });
          map.addLayer({
            id: "impact-junctions-pt",
            type: "circle",
            source: "impact-junctions",
            paint: {
              "circle-radius": 7,
              "circle-color": "#dc2626",
              "circle-stroke-color": "#fff",
              "circle-stroke-width": 2,
            },
          });
        }
        // fit to the network
        try {
          const b = new maplibregl.LngLatBounds();
          roads.features.forEach((f: any) =>
            (f.geometry?.coordinates ?? []).forEach((c: [number, number]) => b.extend(c)),
          );
          if (!b.isEmpty()) map.fitBounds(b, { padding: 40, duration: 400, maxZoom: 17 });
        } catch {
          /* ignore */
        }
      };

      if (map.isStyleLoaded()) draw();
      else map.once("load", draw);
    };
    apply();
  }, [impact]);

  return <div ref={mapRef} style={{ width: "100%", height: 420, borderRadius: 8, overflow: "hidden" }} />;
}

/** Compact impact summary + legend. */
export function ImpactSummary({ impact }: { impact: Impact }) {
  const s = impact.summary;
  const pct = (v: number | null | undefined) =>
    v === null || v === undefined ? "N/A" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
  const cell = {
    flex: "1 1 120px",
    background: "var(--gray-800)",
    borderRadius: 8,
    padding: "10px 14px",
  } as const;
  const big = { fontSize: "1.4em", fontWeight: 700 } as const;
  const lbl = { fontSize: "0.8em", color: "var(--gray-400)" } as const;

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <div style={cell}><div style={big}>{pct(s.travel_time_delta_pct)}</div><div style={lbl}>Travel Time</div></div>
        <div style={cell}><div style={big}>{pct(s.queue_delta_pct)}</div><div style={lbl}>Queue</div></div>
        <div style={cell}><div style={big}>{s.affected_roads ?? 0}</div><div style={lbl}>Affected Roads</div></div>
        <div style={cell}><div style={big}>{s.critical_junctions ?? 0}</div><div style={lbl}>Critical Junctions</div></div>
      </div>
      <div style={{ display: "flex", gap: 16, marginTop: 10, fontSize: "0.85em", flexWrap: "wrap" }}>
        <LegendDot color={ATTR_COLOR.DIRECTLY_AFFECTED} text={`Directly affected (${s.directly_affected ?? 0})`} />
        <LegendDot color={ATTR_COLOR.SECONDARILY_AFFECTED} text={`Secondarily affected (${s.secondarily_affected ?? 0})`} />
        <LegendDot color={ATTR_COLOR.UNCHANGED} text="Unchanged" />
        <LegendDot color="#dc2626" text="Critical junction" round />
      </div>
    </div>
  );
}

function LegendDot({ color, text, round }: { color: string; text: string; round?: boolean }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{
        width: round ? 12 : 16, height: round ? 12 : 4, borderRadius: round ? "50%" : 2,
        background: color, display: "inline-block",
      }} />
      {text}
    </span>
  );
}
