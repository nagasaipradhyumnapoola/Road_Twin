import { useEffect, useRef, useState, useCallback } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

// Reliable OSM raster style specification (works offline/online, no vector font dependencies)
const OSM_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    "osm-tiles": {
      type: "raster",
      tiles: [
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [
    {
      id: "osm-tiles-layer",
      type: "raster",
      source: "osm-tiles",
      minzoom: 0,
      maxzoom: 19,
    },
  ],
};

interface Candidate {
  display_name: string;
  lat: number;
  lon: number;
  importance: number;
}

interface LocationState {
  name: string;
  lat: number;
  lon: number;
  aoi_radius_m: number;
  confirmed: boolean;
}

interface LocationGatewayProps {
  port?: number;
  onConfirmed: (loc: LocationState) => void;
}

export function LocationGateway({ port, onConfirmed }: LocationGatewayProps) {
  const activePort = port ?? (window as unknown as { __rtPort?: number }).__rtPort ?? 8765;
  const API = `http://127.0.0.1:${activePort}`;

  // Search
  const [query, setQuery]           = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [searching, setSearching]   = useState(false);
  const [searchErr, setSearchErr]   = useState("");

  // Coordinates
  const [lat, setLat]               = useState(12.8231);
  const [lon, setLon]               = useState(80.0442);
  const [radius, setRadius]         = useState(500);
  const [siteName, setSiteName]     = useState("");

  // Manual coord inputs (string to allow partial edit)
  const [latStr, setLatStr]         = useState("12.8231");
  const [lonStr, setLonStr]         = useState("80.0442");

  // Pipeline
  const [confirming, setConfirming] = useState(false);
  const [confirmErr, setConfirmErr] = useState("");

  // Map
  const mapRef      = useRef<HTMLDivElement>(null);
  const mapObj      = useRef<maplibregl.Map | null>(null);
  const markerRef   = useRef<maplibregl.Marker | null>(null);
  const circleRef   = useRef<maplibregl.GeoJSONSource | null>(null);

  // ── parse manual inputs safely ───────────────────────────────────────────
  const parseManual = useCallback((): { valid: boolean; lat: number; lon: number } => {
    const lt = parseFloat(latStr.trim());
    const lg = parseFloat(lonStr.trim());
    if (isNaN(lt) || isNaN(lg) || lt < -90 || lt > 90 || lg < -180 || lg > 180) {
      return { valid: false, lat, lon };
    }
    return { valid: true, lat: lt, lon: lg };
  }, [latStr, lonStr, lat, lon]);

  // ── initialise map once ──────────────────────────────────────────────────
  useEffect(() => {
    if (!mapRef.current || mapObj.current) return;

    let map: maplibregl.Map;
    try {
      map = new maplibregl.Map({
        container: mapRef.current,
        style: OSM_STYLE,
        center: [lon, lat],
        zoom: 15,
        minZoom: 4,
        maxZoom: 19,
      });
    } catch (e) {
      console.error("Map initialization error:", e);
      return;
    }

    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(new maplibregl.ScaleControl(), "bottom-left");

    const setupLayers = () => {
      if (!map.getSource("aoi-circle")) {
        map.addSource("aoi-circle", {
          type: "geojson",
          data: buildCircleGeoJSON(lat, lon, radius),
        });
        map.addLayer({
          id: "aoi-fill",
          type: "fill",
          source: "aoi-circle",
          paint: { "fill-color": "#3b82f6", "fill-opacity": 0.08 },
        });
        map.addLayer({
          id: "aoi-outline",
          type: "line",
          source: "aoi-circle",
          paint: { "line-color": "#3b82f6", "line-width": 1.5, "line-dasharray": [4, 3] },
        });
        circleRef.current = map.getSource("aoi-circle") as maplibregl.GeoJSONSource;
      }
    };

    map.on("load", () => {
      setupLayers();

      // Draggable marker
      const el = document.createElement("div");
      el.className = "rt-marker";
      const marker = new maplibregl.Marker({ element: el, draggable: true })
        .setLngLat([lon, lat])
        .addTo(map);

      marker.on("dragend", () => {
        const { lng, lat: lt } = marker.getLngLat();
        updateCoords(lt, lng, "drag");
      });

      markerRef.current = marker;
    });

    map.on("click", (e: maplibregl.MapMouseEvent) => {
      updateCoords(e.lngLat.lat, e.lngLat.lng, "click");
    });

    // Resize observer for flex containers
    const resizeObserver = new ResizeObserver(() => {
      map.resize();
    });
    if (mapRef.current) {
      resizeObserver.observe(mapRef.current);
    }

    setTimeout(() => map.resize(), 150);
    setTimeout(() => map.resize(), 500);

    mapObj.current = map;
    return () => {
      resizeObserver.disconnect();
      map.remove();
      mapObj.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── reverse geocoding on drag / click / manual ──────────────────────────
  const revTimer = useRef<number | null>(null);

  const fetchReverseName = useCallback((lt: number, lg: number) => {
    if (revTimer.current) clearTimeout(revTimer.current);
    revTimer.current = window.setTimeout(async () => {
      try {
        const r = await fetch(`${API}/location/reverse`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lat: lt, lon: lg }),
        });
        if (r.ok) {
          const d = await r.json();
          if (d && d.display_name) {
            setSiteName(d.display_name);
          }
        }
      } catch {
        // silent fallback
      }
    }, 350);
  }, [API]);

  // ── sync marker + circle when coords change ──────────────────────────────
  const updateCoords = useCallback((lt: number, lg: number, src: string) => {
    setLat(lt);
    setLon(lg);
    setLatStr(lt.toFixed(6));
    setLonStr(lg.toFixed(6));
    markerRef.current?.setLngLat([lg, lt]);
    circleRef.current?.setData(buildCircleGeoJSON(lt, lg, radius));
    mapObj.current?.easeTo({ center: [lg, lt], duration: 300 });
    if (src === "drag" || src === "click" || src === "manual") {
      fetchReverseName(lt, lg);
    }
  }, [radius, fetchReverseName]);

  // update circle on radius change
  useEffect(() => {
    circleRef.current?.setData(buildCircleGeoJSON(lat, lon, radius));
  }, [radius, lat, lon]);

  // initial reverse geocode on load
  useEffect(() => {
    fetchReverseName(lat, lon);
  }, [fetchReverseName]);

  // ── geocode ──────────────────────────────────────────────────────────────
  async function doSearch() {
    if (!query.trim()) return;
    setSearching(true);
    setSearchErr("");
    setCandidates([]);
    try {
      const r = await fetch(`${API}/location/geocode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim() }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail ?? `HTTP ${r.status}`);
      }
      const data: Candidate[] = await r.json();
      if (data.length === 0) setSearchErr("No results found. Try a different address.");
      else setCandidates(data);
    } catch (e) {
      setSearchErr(String(e));
    } finally {
      setSearching(false);
    }
  }

  function pickCandidate(c: Candidate) {
    setSiteName(c.display_name.split(",").slice(0, 3).join(","));
    updateCoords(c.lat, c.lon, "geocode");
    setCandidates([]);
    setQuery("");
    mapObj.current?.flyTo({ center: [c.lon, c.lat], zoom: 15, duration: 900 });
  }

  // ── manual coord commit ──────────────────────────────────────────────────
  function commitManual() {
    const { valid, lat: parsedLat, lon: parsedLon } = parseManual();
    if (!valid) return;
    updateCoords(parsedLat, parsedLon, "manual");
    mapObj.current?.flyTo({ center: [parsedLon, parsedLat], zoom: 15, duration: 700 });
  }

  // ── open in maps ─────────────────────────────────────────────────────────
  async function openInMaps() {
    try {
      const { openUrl } = await import("@tauri-apps/plugin-opener");
      await openUrl(`https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}&zoom=15`);
    } catch {
      window.open(`https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}&zoom=15`, "_blank");
    }
  }

  // ── confirm ──────────────────────────────────────────────────────────────
  async function confirmLocation() {
    setConfirming(true);
    setConfirmErr("");

    const parsed = parseManual();
    const finalLat = parsed.valid ? parsed.lat : lat;
    const finalLon = parsed.valid ? parsed.lon : lon;

    try {
      const r = await fetch(`${API}/location/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: siteName.trim() || `${finalLat.toFixed(4)}, ${finalLon.toFixed(4)}`,
          lat: finalLat,
          lon: finalLon,
          aoi_radius_m: radius,
          confirmation_method: "user",
        }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail ?? `HTTP ${r.status}`);
      }
      const data = await r.json();
      onConfirmed(data.location);
    } catch (e) {
      setConfirmErr(String(e));
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="lg-shell">
      {/* ── left panel ── */}
      <aside className="lg-panel">
        <div className="lg-section">
          <p className="lg-label">Search address</p>
          <div className="lg-search-row">
            <input
              id="location-search"
              className="lg-input"
              placeholder="e.g. GST Road, Chennai"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && doSearch()}
            />
            <button className="btn-primary" onClick={doSearch} disabled={searching}>
              {searching ? "…" : "Search"}
            </button>
          </div>

          {searchErr && <p className="lg-hint err">{searchErr}</p>}

          {candidates.length > 0 && (
            <ul className="lg-candidates">
              {candidates.map((c, i) => (
                <li key={i} className="lg-candidate" onClick={() => pickCandidate(c)}>
                  <span className="cand-name">{c.display_name}</span>
                  <span className="cand-coords">
                    {c.lat.toFixed(4)}, {c.lon.toFixed(4)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="lg-divider" />

        <div className="lg-section">
          <p className="lg-label">Manual coordinates</p>
          <div className="lg-coord-grid">
            <label className="lg-coord-label">Lat</label>
            <input
              className="lg-input mono"
              value={latStr}
              onChange={(e) => setLatStr(e.target.value)}
              onBlur={commitManual}
              onKeyDown={(e) => e.key === "Enter" && commitManual()}
            />
            <label className="lg-coord-label">Lon</label>
            <input
              className="lg-input mono"
              value={lonStr}
              onChange={(e) => setLonStr(e.target.value)}
              onBlur={commitManual}
              onKeyDown={(e) => e.key === "Enter" && commitManual()}
            />
          </div>
          <p className="lg-hint">Or drag the marker on the map · Click to place</p>
        </div>

        <div className="lg-divider" />

        <div className="lg-section">
          <p className="lg-label">AOI radius: {radius} m</p>
          <input
            id="aoi-radius"
            type="range" min="200" max="2000" step="50"
            value={radius}
            className="lg-slider"
            onChange={(e) => setRadius(Number(e.target.value))}
          />
          <p className="lg-hint">Area of interest downloaded from OSM</p>
        </div>

        <div className="lg-divider" />

        <div className="lg-section">
          <p className="lg-label">Site name</p>
          <input
            className="lg-input"
            value={siteName}
            onChange={(e) => setSiteName(e.target.value)}
            placeholder="e.g. GST Road, Chennai"
          />
        </div>

        <div className="lg-coord-display">
          <span className="cd-field">{lat.toFixed(6)}° N</span>
          <span className="cd-sep">·</span>
          <span className="cd-field">{lon.toFixed(6)}° E</span>
          <button className="btn-ghost" onClick={openInMaps} title="Open in OpenStreetMap">↗</button>
        </div>

        {confirmErr && <p className="lg-hint err" style={{ marginTop: 8 }}>{confirmErr}</p>}

        <button
          id="confirm-location-btn"
          className="btn-confirm"
          onClick={confirmLocation}
          disabled={confirming}
        >
          {confirming ? "Saving…" : "✓ Confirm Location"}
        </button>
      </aside>

      {/* ── map ── */}
      <div ref={mapRef} className="lg-map" />
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────────

function buildCircleGeoJSON(lat: number, lon: number, radiusM: number) {
  const n = 64;
  const coords: [number, number][] = [];
  for (let i = 0; i <= n; i++) {
    const angle = (i / n) * Math.PI * 2;
    const dLat  = (radiusM / 111320) * Math.cos(angle);
    const dLon  = (radiusM / (111320 * Math.cos((lat * Math.PI) / 180))) * Math.sin(angle);
    coords.push([lon + dLon, lat + dLat]);
  }
  return {
    type: "FeatureCollection" as const,
    features: [{
      type: "Feature" as const,
      properties: {},
      geometry: { type: "Polygon" as const, coordinates: [coords] },
    }],
  };
}

