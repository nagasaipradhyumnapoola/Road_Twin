/* RoadTwin — P10 Acceleration Proof panel
 * Shows the modeling benchmark: network size, automated stage timings, and the
 * human effort that remains. Real measured values only — no manual baseline,
 * no "X times faster" claim (enforced server-side in core/benchmark.py).
 */
import { useCallback, useEffect, useState } from "react";

interface NetworkSize { roads: number; junctions: number; lanes: number; }
interface Timings {
  acquisition_s?: number;
  model_generation_s?: number;
  compilation_s?: number;
  export_s?: number;
  simulation_s?: number;
  total_s?: number;
}
interface HumanActions {
  location_confirmation: number;
  evidence_reviews: number;
  manual_edits: number;
}
interface BenchmarkRecord {
  benchmark_id: string;
  location?: { name?: string } | null;
  network?: NetworkSize | null;
  timings: Timings;
  human_actions: HumanActions;
  seeds?: number | null;
  sumo_version?: string | null;
  source?: string;
}

const STAGE_LABELS: [keyof Timings, string][] = [
  ["acquisition_s", "OSM Acquisition"],
  ["model_generation_s", "Twin Generation"],
  ["compilation_s", "Compilation"],
  ["export_s", "Export"],
];

function fmtSecs(s: number | undefined): string {
  if (s === undefined || s === null) return "—";
  if (s > 0 && s < 0.1) return "<0.1 s";
  return `${s.toFixed(1)} s`;
}

export function BenchmarkPanel({ port }: { port: number }) {
  const [record, setRecord] = useState<BenchmarkRecord | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "empty" | "error">("loading");
  const [error, setError] = useState<string>("");

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setState("loading");
      try {
        const r = await fetch(`http://127.0.0.1:${port}/benchmark`, { signal });
        if (r.status === 404) { setState("empty"); return; }
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d: BenchmarkRecord = await r.json();
        setRecord(d);
        setState("ready");
      } catch (e) {
        if ((e as { name?: string }).name === "AbortError") return;
        setError(String(e));
        setState("error");
      }
    },
    [port],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  return (
    <div className="pipeline-card benchmark-card">
      <div className="bench-head">
        <div>
          <h2>Modeling Benchmark</h2>
          <p className="ws-hint" style={{ marginBottom: 0 }}>
            How much of the road-network modeling is automated, and how much human
            effort remains. Every value below is measured from the actual run.
          </p>
        </div>
        <button className="btn-ghost" onClick={() => load()} title="Reload benchmark">
          ↻ Refresh
        </button>
      </div>

      {state === "loading" && <p className="ws-hint">Loading benchmark…</p>}

      {state === "empty" && (
        <p className="ws-hint">
          No benchmark recorded yet. Run the pipeline (Acquire → Build → Export)
          and it will appear here.
        </p>
      )}

      {state === "error" && (
        <p className="ws-hint err">Could not load benchmark: {error}</p>
      )}

      {state === "ready" && record && (
        <>
          {/* NETWORK */}
          <div className="bench-section-label">Network</div>
          <div className="stats-grid">
            <div className="stat-cell">
              <span className="stat-val">{record.network?.roads ?? "—"}</span>
              <span className="stat-key">Roads</span>
            </div>
            <div className="stat-cell">
              <span className="stat-val">{record.network?.junctions ?? "—"}</span>
              <span className="stat-key">Junctions</span>
            </div>
            <div className="stat-cell">
              <span className="stat-val">{record.network?.lanes ?? "—"}</span>
              <span className="stat-key">Lanes</span>
            </div>
          </div>

          {/* AUTOMATED PROCESSING */}
          <div className="bench-section-label">Automated Processing</div>
          <div className="bench-rows">
            {STAGE_LABELS.map(([key, label]) => (
              <div className="bench-row" key={key}>
                <span className="bench-row-label">{label}</span>
                <span className="bench-row-val">{fmtSecs(record.timings[key])}</span>
              </div>
            ))}
            <div className="bench-row bench-row-total">
              <span className="bench-row-label">TOTAL</span>
              <span className="bench-row-val">{fmtSecs(record.timings.total_s)}</span>
            </div>
            {record.timings.simulation_s !== undefined && (
              <div className="bench-row bench-row-aside">
                <span className="bench-row-label">
                  Simulation{record.seeds ? ` (${record.seeds} seeds)` : ""}
                </span>
                <span className="bench-row-val">{fmtSecs(record.timings.simulation_s)}</span>
              </div>
            )}
          </div>

          {/* HUMAN INPUT */}
          <div className="bench-section-label">Human Input</div>
          <div className="stats-grid">
            <div className="stat-cell">
              <span className="stat-val">{record.human_actions.location_confirmation}</span>
              <span className="stat-key">Location Confirmation</span>
            </div>
            <div className="stat-cell">
              <span className="stat-val">{record.human_actions.evidence_reviews}</span>
              <span className="stat-key">Evidence Reviews</span>
            </div>
            <div className="stat-cell">
              <span className="stat-val">{record.human_actions.manual_edits}</span>
              <span className="stat-key">Manual Edits</span>
            </div>
          </div>

          <p className="bench-footnote">
            Measured stage timings and counts only — no manual baseline is assumed
            and no speed-multiplier is claimed.
            {record.sumo_version ? ` · ${record.sumo_version}` : ""}
            {record.source === "benchmark" ? " · bundled benchmark project" : ""}
          </p>
        </>
      )}
    </div>
  );
}
