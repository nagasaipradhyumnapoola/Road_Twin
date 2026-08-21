/**
 * ExperimentWorkspace — Phase 6: The lane-closure experiment UI.
 *
 * Flow:
 *   1. Load network edges → populate edge + lane selectors
 *   2. Generate demand (period from config, with override)
 *   3. RUN EXPERIMENT → baseline vs closure across seeds
 *   4. Display comparison table with delta%, significance verdict
 *   5. Export ZIP
 *
 * Every error path surfaces a clear, actionable message.
 * The UI never fabricates numbers — if the backend says not significant, we say so.
 */
import { useCallback, useEffect, useRef, useState } from "react";

const API = () =>
  `http://127.0.0.1:${(window as unknown as { __rtPort?: number }).__rtPort ?? 8765}`;

// ── types ─────────────────────────────────────────────────────────────────────

interface EdgeInfo {
  num_lanes: number;
  length_m: number;
  from: string;
  to: string;
  lanes: Array<{ id: string; index: number; length: number; speed: number }>;
}

export interface ComparisonRow {
  metric: string;
  unit: string;
  baseline: number | null;
  scenario: number | null;
  delta: number | null;
  delta_pct: number | null;
}

export interface ComparisonResult {
  rows: ComparisonRow[];
  n_seeds: number;
  significant: boolean;
  verdict: string;
}

interface ExperimentResult {
  status: "idle" | "running" | "done" | "error";
  result?: {
    baseline: Record<string, unknown>;
    closure: Record<string, unknown>;
    comparison: ComparisonResult;
    table: string;
  };
  scenario?: {
    edge_id: string;
    lane_id: string;
    lane_index: number;
    lanes_on_edge: number;
    actual_closed_length_m: number;
    begin: number;
    end: number;
    note: string;
  };
  detail?: string;
}

type Step =
  | "load_edges"
  | "configure"
  | "demand"
  | "running"
  | "done"
  | "error";

interface ExperimentWorkspaceProps {
  onSimulating?: () => void;
  onExporting?: () => void;
  onComplete?: () => void;
}

// ── component ─────────────────────────────────────────────────────────────────

export function ExperimentWorkspace({
  onSimulating,
  onExporting,
  onComplete,
}: ExperimentWorkspaceProps = {}) {
  // Network edges
  const [edges, setEdges]             = useState<Record<string, EdgeInfo>>({});
  const [recommended, setRecommended] = useState<{ edge_id: string; num_lanes: number; length_m: number } | null>(null);
  const [edgesLoading, setEdgesLoading] = useState(true);
  const [edgesError, setEdgesError]   = useState("");

  // Configuration
  const [selectedEdge, setSelectedEdge] = useState("");
  const [selectedLane, setSelectedLane] = useState(0);
  const [period, setPeriod]           = useState(3.0);    // calibrated demand period (config.py SIM.period)
  const [seedsStr, setSeedsStr]       = useState(
    "42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61"  // calibrated 20 seeds (config.py SIM.seeds = range(42,62))
  );

  // Demand
  const [demandStatus, setDemandStatus] = useState<"none" | "generating" | "ready" | "error">("none");
  const [vehicleCount, setVehicleCount] = useState<number | null>(null);
  const [demandWarning, setDemandWarning] = useState("");

  // Experiment
  const [step, setStep]               = useState<Step>("load_edges");
  const [running, setRunning]         = useState(false);
  const [result, setResult]           = useState<ExperimentResult | null>(null);
  const [log, setLog]                 = useState<string[]>([]);

  // ZIP export
  const [exporting, setExporting]     = useState(false);
  const [zipPath, setZipPath]         = useState("");
  const [zipError, setZipError]       = useState("");

  const logRef = useRef<HTMLPreElement>(null);

  function addLog(msg: string) {
    setLog((prev) => [...prev, msg]);
  }

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current)
      logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  // ── load edges on mount ──────────────────────────────────────────────────
  const loadEdges = useCallback(async () => {
    setEdgesLoading(true);
    setEdgesError("");
    try {
      const r = await fetch(`${API()}/network/edges`);
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail ?? `HTTP ${r.status}`);
      }
      const data = await r.json();
      setEdges(data.edges ?? {});
      setRecommended(data.recommended ?? null);

      // Pre-select recommended edge
      if (data.recommended?.edge_id) {
        const eid = data.recommended.edge_id;
        setSelectedEdge(eid);
        const edgeInfo = data.edges?.[eid];
        if (edgeInfo) setSelectedLane(edgeInfo.num_lanes - 1); // topmost by default
      } else {
        const first = Object.keys(data.edges ?? {})[0];
        if (first) {
          setSelectedEdge(first);
          setSelectedLane((data.edges[first].num_lanes ?? 1) - 1);
        }
      }
      setStep("configure");
    } catch (e) {
      setEdgesError(String(e));
      setStep("error");
    } finally {
      setEdgesLoading(false);
    }
  }, []);

  useEffect(() => { loadEdges(); }, [loadEdges]);

  // When edge changes, reset lane to topmost
  function onEdgeChange(eid: string) {
    setSelectedEdge(eid);
    const info = edges[eid];
    if (info) setSelectedLane(info.num_lanes - 1);
    setDemandStatus("none");
    setResult(null);
    setLog([]);
  }

  function parseSeedsStr(s: string): number[] {
    return s.split(",").map((x) => parseInt(x.trim())).filter((n) => !isNaN(n));
  }

  // ── demand generation ────────────────────────────────────────────────────
  async function generateDemand(force = false) {
    setDemandStatus("generating");
    setDemandWarning("");
    addLog(`→ Generating traffic demand (period=${period}, force=${force})…`);
    try {
      const r = await fetch(`${API()}/demand/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ period, fringe_factor: 10.0, force }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail ?? `HTTP ${r.status}`);
      }
      const data = await r.json();
      setVehicleCount(data.vehicle_count);
      if (data.warning) setDemandWarning(data.warning);
      const cached = data.cached ? " (cached)" : "";
      addLog(`✓ Demand ready — ${data.vehicle_count} vehicles${cached}`);
      if (data.warning) addLog(`⚠ ${data.warning}`);
      setDemandStatus("ready");
    } catch (e) {
      addLog(`✗ Demand failed: ${String(e)}`);
      setDemandStatus("error");
    }
  }

  // ── run experiment ───────────────────────────────────────────────────────
  async function runExperiment() {
    if (!selectedEdge) return;
    const parsedSeeds = parseSeedsStr(seedsStr);
    setRunning(true);
    setStep("running");
    setResult(null);
    onSimulating?.();

    addLog(`→ Running experiment: edge=${selectedEdge}  lane=${selectedLane}  seeds=${parsedSeeds.join(",")}`);
    addLog(`  Baseline: all lanes open`);
    addLog(`  Closure:  lane ${selectedLane} of ${selectedEdge} closed (t=300s–3600s)`);
    addLog(`  This will take ~${parsedSeeds.length * 20}–${parsedSeeds.length * 60}s…`);

    try {
      const r = await fetch(`${API()}/experiment/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          edge_id: selectedEdge,
          lane_index: selectedLane,
          seeds: parsedSeeds,
        }),
      });

      const data: ExperimentResult = await r.json();

      if (!r.ok) {
        const detail = (data as unknown as { detail?: string }).detail ?? `HTTP ${r.status}`;
        throw new Error(detail);
      }

      setResult(data);
      setStep("done");
      onComplete?.();
      const cmp = data.result?.comparison;
      if (cmp) {
        addLog(`✓ Experiment complete — ${cmp.n_seeds} seeds`);
        addLog(`  Verdict: ${cmp.verdict}`);
        if (!cmp.significant) {
          addLog(`⚠ NOT SIGNIFICANT — lower demand period or pick a more critical edge`);
        }
      }
    } catch (e) {
      addLog(`✗ Experiment failed: ${String(e)}`);
      setResult({ status: "error", detail: String(e) });
      setStep("error");
    } finally {
      setRunning(false);
    }
  }

  // ── export zip ───────────────────────────────────────────────────────────
  async function exportZip() {
    setExporting(true);
    onExporting?.();
    setZipError("");
    setZipPath("");
    try {
      const r = await fetch(`${API()}/export/zip`, { method: "POST" });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail ?? `HTTP ${r.status}`);
      }
      const data = await r.json();
      setZipPath(data.zip_path);
      onComplete?.();
    } catch (e) {
      setZipError(String(e));
    } finally {
      setExporting(false);
    }
  }

  // ── open zip in explorer ─────────────────────────────────────────────────
  async function openInExplorer(path: string) {
    try {
      const { openPath } = await import("@tauri-apps/plugin-opener");
      // Open containing folder
      const folder = path.replace(/[/\\][^/\\]+$/, "");
      await openPath(folder);
    } catch {
      /* fallback: nothing */
    }
  }

  // ── rendering ────────────────────────────────────────────────────────────
  const edgeInfo = edges[selectedEdge];

  return (
    <div className="exp-shell">
      {/* ── left: configuration panel ── */}
      <aside className="exp-panel">
        <div className="exp-section">
          <h3 className="exp-section-title">① Select Road &amp; Lane</h3>

          {edgesLoading && <p className="exp-hint">Loading network edges…</p>}
          {edgesError && <p className="exp-hint err">{edgesError}</p>}

          {!edgesLoading && !edgesError && (
            <>
              {recommended && (
                <div className="exp-rec-badge">
                  Recommended: <strong>{recommended.edge_id}</strong>&nbsp;
                  ({recommended.num_lanes} lanes, {recommended.length_m}m)
                </div>
              )}

              <label className="exp-label" htmlFor="edge-select">Road (edge)</label>
              <select
                id="edge-select"
                className="exp-select"
                value={selectedEdge}
                onChange={(e) => onEdgeChange(e.target.value)}
              >
                {Object.entries(edges).map(([eid, info]) => (
                  <option key={eid} value={eid}>
                    {eid} — {info.num_lanes} lanes, {info.length_m}m
                  </option>
                ))}
              </select>

              {edgeInfo && (
                <>
                  <label className="exp-label" htmlFor="lane-select">
                    Lane to close&nbsp;
                    <span className="exp-hint-inline">(0 = rightmost)</span>
                  </label>
                  <select
                    id="lane-select"
                    className="exp-select"
                    value={selectedLane}
                    onChange={(e) => setSelectedLane(Number(e.target.value))}
                  >
                    {edgeInfo.lanes.map((ln) => (
                      <option key={ln.id} value={ln.index}>
                        Lane {ln.index} — {ln.length.toFixed(0)}m @ {(ln.speed * 3.6).toFixed(0)} km/h
                      </option>
                    ))}
                  </select>

                  <div className="exp-edge-info">
                    <InfoRow label="Closure length" value={`${edgeInfo.length_m} m`} note="full edge — SUMO limitation" />
                    <InfoRow label="Lanes on edge" value={String(edgeInfo.num_lanes)} />
                    <InfoRow label="Lane being closed" value={`${selectedEdge}_${selectedLane}`} />
                  </div>
                </>
              )}
            </>
          )}
        </div>

        <div className="exp-divider" />

        <div className="exp-section">
          <h3 className="exp-section-title">② Traffic Demand</h3>
          <label className="exp-label" htmlFor="period-input">
            Period (s/veh)&nbsp;
            <span className="exp-hint-inline">lower = more traffic</span>
          </label>
          <div className="exp-row">
            <input
              id="period-input"
              type="number" min="0.1" max="5" step="0.05"
              className="exp-input mono"
              value={period}
              onChange={(e) => setPeriod(parseFloat(e.target.value))}
            />
            <button
              className="btn-primary"
              onClick={() => generateDemand(false)}
              disabled={demandStatus === "generating"}
            >
              {demandStatus === "generating" ? "Generating…" : "Generate"}
            </button>
            {demandStatus === "ready" && (
              <button className="btn-ghost" onClick={() => generateDemand(true)} title="Re-generate">↺</button>
            )}
          </div>
          {vehicleCount !== null && (
            <p className="exp-hint">{vehicleCount} vehicles in routes file</p>
          )}
          {demandWarning && <p className="exp-hint err">{demandWarning}</p>}

          <label className="exp-label" style={{ marginTop: 10 }} htmlFor="seeds-input">Seeds (comma-separated)</label>
          <input
            id="seeds-input"
            className="exp-input mono"
            value={seedsStr}
            onChange={(e) => setSeedsStr(e.target.value)}
          />
          <p className="exp-hint">{parseSeedsStr(seedsStr).length} seeds → each run takes ~20-60s</p>
        </div>

        <div className="exp-divider" />

        <div className="exp-section">
          <h3 className="exp-section-title">③ Run Experiment</h3>
          <p className="exp-hint" style={{ marginBottom: 12 }}>
            Identical network, routes, seeds — only the rerouter additional-file differs.
            The delta is causal.
          </p>
          <button
            id="run-experiment-btn"
            className="btn-confirm"
            onClick={runExperiment}
            disabled={running || demandStatus !== "ready" || !selectedEdge}
          >
            {running ? "⏳ Simulating…" : "▶ Run Experiment"}
          </button>
          {demandStatus !== "ready" && !running && (
            <p className="exp-hint err" style={{ marginTop: 6 }}>Generate demand first (step ②)</p>
          )}
        </div>
      </aside>

      {/* ── right: results panel ── */}
      <section className="exp-results">
        {/* Log */}
        {log.length > 0 && (
          <pre className="exp-log" ref={logRef}>
            {log.join("\n")}
          </pre>
        )}

        {/* Results */}
        {result?.status === "done" && result.result && (
          <div className="exp-result-card">
            <ResultTable comparison={result.result.comparison} scenario={result.scenario} />

            {/* ZIP export */}
            <div className="exp-export-row">
              <button
                id="export-zip-btn"
                className="btn-primary lg"
                onClick={exportZip}
                disabled={exporting}
              >
                {exporting ? "Packaging…" : "⬇ Export RoadTwin_Project.zip"}
              </button>
              {zipPath && (
                <button className="btn-ghost" onClick={() => openInExplorer(zipPath)}>
                  Open folder ↗
                </button>
              )}
            </div>
            {zipPath && (
              <p className="exp-hint" style={{ marginTop: 6 }}>
                Saved: <code>{zipPath}</code>
              </p>
            )}
            {zipError && <p className="exp-hint err">{zipError}</p>}
          </div>
        )}

        {result?.status === "error" && (
          <div className="exp-error-card">
            <h3>Experiment Failed</h3>
            <pre className="exp-error-msg">{result.detail}</pre>
            <p className="exp-hint">
              Common causes: single-lane edge selected, invalid lane index, SUMO not on PATH.
            </p>
          </div>
        )}

        {step === "configure" && !running && !result && (
          <div className="exp-idle-card">
            <div className="exp-idle-icon">⚗</div>
            <h3>Lane Closure Experiment</h3>
            <p>
              Select a road and lane, generate traffic demand, then run the experiment
              to see how closing a lane affects travel time, queue length, and
              completed vehicles — across multiple random seeds.
            </p>
            <p className="exp-hint" style={{ marginTop: 12 }}>
              The experiment is controlled: same network, same routes, same seeds.
              Only a rerouter additional-file differs, so the delta is causal.
            </p>
          </div>
        )}
      </section>
    </div>
  );
}

// ── sub-components ────────────────────────────────────────────────────────────

function InfoRow({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="exp-info-row">
      <span className="exp-info-label">{label}</span>
      <span className="exp-info-value">
        {value}
        {note && <span className="exp-info-note"> ({note})</span>}
      </span>
    </div>
  );
}

export function ResultTable({
  comparison,
  scenario,
}: {
  comparison: ComparisonResult;
  scenario?: ExperimentResult["scenario"];
}) {
  const sig = comparison.significant;

  return (
    <div className="result-table-wrapper">
      <div className={`result-sig-banner ${sig ? "sig-yes" : "sig-no"}`}>
        {sig ? "✓ SIGNIFICANT" : "⚠ NOT SIGNIFICANT"}
        <span className="result-sig-detail"> — {comparison.verdict}</span>
      </div>

      <div className="result-seeds-badge">
        Mean of {comparison.n_seeds} seed{comparison.n_seeds !== 1 ? "s" : ""}
      </div>

      <table className="result-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th>Baseline</th>
            <th>Closure</th>
            <th>Delta</th>
            <th>Δ%</th>
          </tr>
        </thead>
        <tbody>
          {comparison.rows.map((row) => {
            const deltaSign = (row.delta_pct ?? 0) > 0 ? "positive" : "negative";
            return (
              <tr key={row.metric}>
                <td className="result-metric-name">{row.metric}</td>
                <td className="result-num">
                  {row.baseline !== null ? `${row.baseline.toFixed(1)}${row.unit}` : "—"}
                </td>
                <td className="result-num">
                  {row.scenario !== null ? `${row.scenario.toFixed(1)}${row.unit}` : "—"}
                </td>
                <td className="result-num">
                  {row.delta !== null ? `${row.delta > 0 ? "+" : ""}${row.delta.toFixed(1)}${row.unit}` : "—"}
                </td>
                <td className={`result-delta ${row.delta_pct !== null ? deltaSign : ""}`}>
                  {row.delta_pct !== null
                    ? `${row.delta_pct > 0 ? "+" : ""}${row.delta_pct.toFixed(1)}%`
                    : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {scenario && (
        <div className="result-scenario-note">
          <strong>Scenario:</strong> Lane {scenario.lane_index} of{" "}
          <code>{scenario.edge_id}</code> closed ({scenario.actual_closed_length_m}m)
          from t={scenario.begin}s to t={scenario.end}s.{" "}
          <em>{scenario.note}</em>
        </div>
      )}
    </div>
  );
}
