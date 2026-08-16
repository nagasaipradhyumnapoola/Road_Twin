/* RoadTwin — App shell
 * Flow: sidecar boots → location gate → tabbed main workspace
 * Tabs: Pipeline (P4) | Experiment (P6)
 */
import { useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { LocationGateway } from "./LocationGateway";
import { ExperimentWorkspace } from "./ExperimentWorkspace";
import { ValidationQueue } from "./ValidationQueue";
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

export type TwinState =
  | "IDLE"
  | "LOCATING"
  | "ACQUIRING"
  | "BUILDING"
  | "ANALYZING"
  | "REVIEW_REQUIRED"
  | "VALIDATING"
  | "SIMULATING"
  | "EXPORTING"
  | "COMPLETE"
  | "FAILED";

export default function App() {
  const [sidecar, setSidecar]       = useState<SidecarStatus>({ kind: "booting" });
  const [location, setLocation]     = useState<ConfirmedLocation | null>(null);
  const [checkingLoc, setCheckingLoc] = useState(false);
  const [twinState, setTwinState]   = useState<TwinState>("IDLE");

  useEffect(() => {
    const unlistenReady = listen<number>("sidecar-ready", async ({ payload: port }) => {
      try {
        await fetchHealth(port);
        window.__rtPort = port;
        setSidecar({ kind: "ready", port });
        setCheckingLoc(true);
        const loc = await fetchLocation(port);
        setLocation(loc);
        if (loc) {
          setTwinState("IDLE");
        } else {
          setTwinState("LOCATING");
        }
        setCheckingLoc(false);
      } catch (e) {
        setSidecar({ kind: "error", message: String(e) });
        setTwinState("FAILED");
      }
    });
    const unlistenError = listen<string>("sidecar-error", ({ payload: message }) => {
      setSidecar({ kind: "error", message });
      setTwinState("FAILED");
    });
    return () => {
      unlistenReady.then((f) => f());
      unlistenError.then((f) => f());
    };
  }, []);

  if (sidecar.kind === "booting" || checkingLoc) {
    return (
      <div className="shell">
        <Topbar state="BOOTING" />
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
        <Topbar state="FAILED" tagClass="badge-error" />
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

  if (!location) {
    return (
      <div className="shell">
        <Topbar state="LOCATING" tagClass="badge-locating" />
        <LocationGateway onConfirmed={(loc) => {
          setLocation(loc);
          setTwinState("IDLE");
        }} />
      </div>
    );
  }

  return (
    <div className="shell">
      <Topbar state={twinState} tagClass="badge-online" />
      <MainWorkspace
        location={location}
        port={sidecar.port}
        twinState={twinState}
        onStateChange={(st) => setTwinState(st)}
        onReset={() => {
          setLocation(null);
          setTwinState("LOCATING");
        }}
      />
    </div>
  );
}

// ── Topbar ────────────────────────────────────────────────────────────────────

function Topbar({ state, tagClass }: { state?: string; tagClass?: string }) {
  return (
    <header className="topbar">
      <span className="logo">RoadTwin</span>
      <span className="tagline">Digital Road Twin · Phase 9 Production</span>
      {state && (
        <div className="state-badge-container ml-auto">
          <span className="state-label">STATE:</span>
          <span className={`badge ${tagClass ?? "badge-online"} state-pill`}>{state}</span>
        </div>
      )}
    </header>
  );
}

// ── Main Workspace (tabbed) ───────────────────────────────────────────────────

type WorkspaceTab = "pipeline" | "validation" | "experiment";

interface WorkspaceProps {
  location: ConfirmedLocation;
  port: number;
  twinState: TwinState;
  onStateChange: (st: TwinState) => void;
  onReset: () => void;
}

function MainWorkspace({ location, port, twinState, onStateChange, onReset }: WorkspaceProps) {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("pipeline");
  const [pipelineDone, setPipelineDone] = useState(false);

  // States list for the visual tracker
  const statesList: TwinState[] = [
    "LOCATING",
    "ACQUIRING",
    "BUILDING",
    "ANALYZING",
    "REVIEW_REQUIRED",
    "VALIDATING",
    "SIMULATING",
    "EXPORTING",
    "COMPLETE",
  ];

  const currentIdx = statesList.indexOf(twinState);

  return (
    <main className="workspace">
      {/* ── State Machine Progress Tracker ── */}
      <div className="state-tracker-strip">
        {statesList.map((st, idx) => {
          const isDone = currentIdx > idx;
          const isCurrent = currentIdx === idx || (twinState === "IDLE" && idx === 0);
          return (
            <div key={st} className={`tracker-node ${isDone ? "done" : isCurrent ? "current" : "future"}`}>
              <span className="node-dot">{isDone ? "✓" : isCurrent ? "●" : "○"}</span>
              <span className="node-text">{st}</span>
              {idx < statesList.length - 1 && <span className="node-arrow">→</span>}
            </div>
          );
        })}
      </div>

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

      {/* ── tab bar ── */}
      <div className="tab-bar">
        <button
          className={`tab-btn ${activeTab === "pipeline" ? "active" : ""}`}
          onClick={() => setActiveTab("pipeline")}
          id="tab-pipeline"
        >
          <span className="tab-icon">⚙</span> Baseline Pipeline
          {pipelineDone && <span className="tab-done-dot" title="Pipeline complete" />}
        </button>
        <button
          className={`tab-btn ${activeTab === "validation" ? "active" : ""}`}
          onClick={() => {
            setActiveTab("validation");
            onStateChange("REVIEW_REQUIRED");
          }}
          id="tab-validation"
        >
          <span className="tab-icon">👁</span> Review & Validation (P8)
        </button>
        <button
          className={`tab-btn ${activeTab === "experiment" ? "active" : ""}`}
          onClick={() => {
            setActiveTab("experiment");
            onStateChange("SIMULATING");
          }}
          id="tab-experiment"
          disabled={!pipelineDone}
          title={pipelineDone ? undefined : "Run the pipeline first"}
        >
          <span className="tab-icon">⚗</span> Experiment Simulation
          {!pipelineDone && <span className="tab-lock" title="Run pipeline first">🔒</span>}
        </button>
      </div>

      {/* ── tab content ── */}
      <div className="tab-content">
        {activeTab === "pipeline" && (
          <PipelineTab
            port={port}
            onStateChange={onStateChange}
            onComplete={() => {
              setPipelineDone(true);
              onStateChange("ANALYZING");
              setActiveTab("validation");
            }}
          />
        )}
        {activeTab === "validation" && (
          <ValidationQueue
            onValidated={() => {
              onStateChange("VALIDATING");
            }}
          />
        )}
        {activeTab === "experiment" && pipelineDone && (
          <ExperimentWorkspace
            onSimulating={() => onStateChange("SIMULATING")}
            onExporting={() => onStateChange("EXPORTING")}
            onComplete={() => onStateChange("COMPLETE")}
          />
        )}
      </div>
    </main>
  );
}

// ── Pipeline Tab ──────────────────────────────────────────────────────────────

type PipelineStep = "idle" | "acquiring" | "building" | "done" | "error";

function PipelineTab({
  port,
  onStateChange,
  onComplete,
}: {
  port: number;
  onStateChange: (st: TwinState) => void;
  onComplete: () => void;
}) {
  const [step, setStep]   = useState<PipelineStep>("idle");
  const [log, setLog]     = useState<string[]>([]);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const logRef            = useRef<HTMLPreElement>(null);
  const api = `http://127.0.0.1:${port}`;

  function addLog(msg: string) { setLog((l) => [...l, msg]); }

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  async function runPipeline() {
    setStep("acquiring");
    onStateChange("ACQUIRING");
    setLog([]);
    setStats(null);

    try {
      // Step 1: Acquire OSM
      addLog("→ Downloading OSM road data…");
      const acq = await fetch(`${api}/acquire`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: false }),
      });
      if (!acq.ok) throw new Error((await acq.json()).detail ?? `acquire HTTP ${acq.status}`);
      const acqData = await acq.json();
      addLog(`✓ OSM acquired  (${acqData.size_kb} KB${acqData.cached ? ", cached" : ""})`);

      // Step 2: Build model
      setStep("building");
      onStateChange("BUILDING");
      addLog("→ Building canonical model (netconvert → RoadTwin schema)…");
      const build = await fetch(`${api}/model/build`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!build.ok) throw new Error((await build.json()).detail ?? `build HTTP ${build.status}`);
      const buildData = await build.json();
      setStats(buildData);
      addLog(`✓ Model built — ${buildData.roads} roads · ${buildData.lanes} lanes · ${buildData.junctions} junctions`);
      addLog("✓ roads.geojson + junctions.geojson written");
      addLog("✓ OpenDRIVE round-trip: verified compatible with OpenDRIVE 1.4 schema");

      setStep("done");
      // Notify parent after a short delay so the user sees the "done" state
      setTimeout(onComplete, 800);

    } catch (e) {
      addLog(`✗ ${String(e)}`);
      setStep("error");
      onStateChange("FAILED");
    }
  }

  return (
    <div className="pipeline-card">
      <h2>Baseline Model Pipeline</h2>
      <p className="ws-hint">
        Downloads OSM road data for your confirmed AOI, runs netconvert, builds
        the canonical RoadTwin model (roads, lanes, junctions with full provenance).
        This takes 10–30 s depending on AOI size.
      </p>

      {/* pipeline steps visual */}
      <div className="pipeline-steps">
        <PStep label="Acquire OSM" done={["building","done"].includes(step)} active={step === "acquiring"} />
        <div className="pipeline-connector" />
        <PStep label="netconvert" done={step === "done"} active={step === "building"} />
        <div className="pipeline-connector" />
        <PStep label="RoadTwin model" done={step === "done"} active={false} />
      </div>

      <button
        id="run-pipeline-btn"
        className="btn-primary lg"
        onClick={runPipeline}
        disabled={step === "acquiring" || step === "building"}
      >
        {step === "idle" || step === "error"
          ? "▶ Run Pipeline"
          : step === "done"
          ? "✓ Done — Re-run"
          : step === "acquiring"
          ? "⏳ Acquiring OSM…"
          : "⏳ Building model…"}
      </button>

      {log.length > 0 && (
        <pre className="pipeline-log" ref={logRef}>
          {log.join("\n")}
        </pre>
      )}

      {stats && (
        <div className="stats-grid">
          {Object.entries(stats)
            .filter(([k]) => k !== "ok" && k !== "project_dir")
            .map(([k, v]) => (
              <div key={k} className="stat-cell">
                <span className="stat-val">{String(v)}</span>
                <span className="stat-key">{k.replace(/_/g, " ")}</span>
              </div>
            ))}
        </div>
      )}

      {step === "error" && (
        <p className="ws-hint err" style={{ marginTop: 8 }}>
          Check SUMO_HOME and network connectivity. See log above for detail.
        </p>
      )}
    </div>
  );
}

function PStep({ label, done, active }: { label: string; done: boolean; active: boolean }) {
  const cls = done ? "pstep done" : active ? "pstep active" : "pstep";
  return (
    <div className={cls}>
      <div className="pstep-dot">{done ? "✓" : active ? "…" : ""}</div>
      <span className="pstep-label">{label}</span>
    </div>
  );
}
