/* RoadTwin — Phase 3 App
 * Flow: sidecar boots → location gate (if not confirmed) → main UI
 */
import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { LocationGateway } from "./LocationGateway";
import "./App.css";

declare global {
  interface Window { __rtPort?: number; }
}

type SidecarStatus =
  | { kind: "booting" }
  | { kind: "ready"; port: number }
  | { kind: "error"; message: string };

interface ConfirmedLocation {
  name: string; lat: number; lon: number;
  aoi_radius_m: number; confirmed: boolean;
}

async function fetchHealth(port: number) {
  const r = await fetch(`http://127.0.0.1:${port}/health`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function fetchLocation(port: number): Promise<ConfirmedLocation | null> {
  try {
    const r = await fetch(`http://127.0.0.1:${port}/location`);
    if (!r.ok) return null;
    const d = await r.json();
    return d.confirmed ? d : null;
  } catch { return null; }
}

export default function App() {
  const [sidecar, setSidecar]     = useState<SidecarStatus>({ kind: "booting" });
  const [location, setLocation]   = useState<ConfirmedLocation | null>(null);
  const [checkingLoc, setCheckingLoc] = useState(false);

  useEffect(() => {
    const unlistenReady = listen<number>("sidecar-ready", async ({ payload: port }) => {
      try {
        await fetchHealth(port);
        window.__rtPort = port;
        setSidecar({ kind: "ready", port });

        setCheckingLoc(true);
        const loc = await fetchLocation(port);
        setLocation(loc);
        setCheckingLoc(false);
      } catch (e) {
        setSidecar({ kind: "error", message: String(e) });
      }
    });

    const unlistenError = listen<string>("sidecar-error", ({ payload: message }) => {
      setSidecar({ kind: "error", message });
    });

    return () => {
      unlistenReady.then((f) => f());
      unlistenError.then((f) => f());
    };
  }, []);

  // ── booting ──────────────────────────────────────────────────────────────
  if (sidecar.kind === "booting" || checkingLoc) {
    return (
      <div className="shell">
        <Topbar />
        <div className="stage">
          <div className="status-card booting">
            <div className="spinner" />
            <p>{checkingLoc ? "Checking saved location…" : "Starting core engine…"}</p>
          </div>
        </div>
      </div>
    );
  }

  if (sidecar.kind === "error") {
    return (
      <div className="shell">
        <Topbar />
        <div className="stage">
          <div className="status-card error">
            <div className="icon-err">✗</div>
            <h2>Sidecar error</h2>
            <pre className="error-msg">{sidecar.message}</pre>
          </div>
        </div>
      </div>
    );
  }

  // ── sidecar ready — check location gate ──────────────────────────────────
  if (!location) {
    return (
      <div className="shell">
        <Topbar tag="SET LOCATION" />
        <LocationGateway onConfirmed={(loc) => setLocation(loc)} />
      </div>
    );
  }

  // ── location confirmed — main workspace ──────────────────────────────────
  return (
    <div className="shell">
      <Topbar tag="ONLINE" tagClass="badge-online" />
      <MainWorkspace location={location} port={sidecar.port}
                     onReset={() => setLocation(null)} />
    </div>
  );
}

// ── sub-components ────────────────────────────────────────────────────────────

function Topbar({ tag, tagClass }: { tag?: string; tagClass?: string }) {
  return (
    <header className="topbar">
      <span className="logo">RoadTwin</span>
      <span className="tagline">Digital Road Twin</span>
      {tag && <span className={`badge ${tagClass ?? "badge-starting"} ml-auto`}>{tag}</span>}
    </header>
  );
}

interface WorkspaceProps {
  location: ConfirmedLocation;
  port: number;
  onReset: () => void;
}

type PipelineStep = "idle" | "acquiring" | "building" | "done" | "error";

function MainWorkspace({ location, port, onReset }: WorkspaceProps) {
  const [step, setStep]     = useState<PipelineStep>("idle");
  const [log, setLog]       = useState<string[]>([]);
  const [stats, setStats]   = useState<Record<string, unknown> | null>(null);
  const api = `http://127.0.0.1:${port}`;

  function addLog(msg: string) { setLog((l) => [...l, msg]); }

  async function runPipeline() {
    setStep("acquiring");
    setLog([]);
    setStats(null);

    try {
      addLog("→ Downloading OSM data…");
      const acq = await fetch(`${api}/acquire`, { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: false }) });
      if (!acq.ok) throw new Error((await acq.json()).detail ?? `acquire HTTP ${acq.status}`);
      const acqData = await acq.json();
      addLog(`✓ OSM acquired  ${acqData.size_kb} KB`);

      setStep("building");
      addLog("→ Building canonical model (netconvert)…");
      const build = await fetch(`${api}/model/build`, { method: "POST",
        headers: { "Content-Type": "application/json" }, body: "{}" });
      if (!build.ok) throw new Error((await build.json()).detail ?? `build HTTP ${build.status}`);
      const buildData = await build.json();
      setStats(buildData);
      addLog(`✓ Model built  ${buildData.roads} roads · ${buildData.lanes} lanes · ${buildData.junctions} junctions`);
      setStep("done");
    } catch (e) {
      addLog(`✗ ${String(e)}`);
      setStep("error");
    }
  }

  return (
    <main className="workspace">
      {/* ── location ribbon ── */}
      <div className="location-ribbon">
        <div className="loc-info">
          <span className="loc-name">{location.name}</span>
          <span className="loc-coords">
            {location.lat.toFixed(6)}° N · {location.lon.toFixed(6)}° E ·
            AOI {location.aoi_radius_m} m
          </span>
        </div>
        <button className="btn-ghost" onClick={onReset} title="Change location">✎ Change</button>
      </div>

      {/* ── pipeline card ── */}
      <div className="pipeline-card">
        <h2>Baseline Model Pipeline</h2>
        <p className="ws-hint">
          Downloads OSM road data for your confirmed AOI, compiles it with
          netconvert, and builds the canonical RoadTwin model.
        </p>

        <button
          id="run-pipeline-btn"
          className="btn-primary lg"
          onClick={runPipeline}
          disabled={step === "acquiring" || step === "building"}
        >
          {step === "idle" || step === "error" || step === "done"
            ? "▶ Run Pipeline"
            : step === "acquiring" ? "Acquiring OSM…" : "Building model…"}
        </button>

        {log.length > 0 && (
          <pre className="pipeline-log">
            {log.join("\n")}
          </pre>
        )}

        {stats && (
          <div className="stats-grid">
            {Object.entries(stats).filter(([k]) => k !== "ok" && k !== "project_dir").map(([k, v]) => (
              <div key={k} className="stat-cell">
                <span className="stat-val">{String(v)}</span>
                <span className="stat-key">{k.replace(/_/g, " ")}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
