import { useCallback, useEffect, useState } from "react";
import { ResultTable } from "./ExperimentWorkspace";
import { ImpactMap, ImpactSummary } from "./ImpactMap";
import { InterventionPanel } from "./InterventionPanel";
import { DecisionPanel } from "./DecisionPanel";

const API = () =>
  `http://127.0.0.1:${(window as unknown as { __rtPort?: number }).__rtPort ?? 8765}`;

interface ScenarioParamSpec {
  name: string;
  kind: string;
  required: boolean;
  label: string;
  help?: string;
  default?: number;
  min?: number;
  max?: number;
  step?: number;
}

interface ScenarioTypeSpec {
  type: string;
  label: string;
  help: string;
  params: ScenarioParamSpec[];
}

interface ScenarioSummary {
  kind: "baseline" | "comparison";
  baseline_travel_time_s?: number;
  travel_time_delta_pct?: number;
  significant?: boolean;
}

interface Scenario {
  scenario_id: string;
  name: string;
  type: string;
  parameters: Record<string, any>;
  seeds: number[];
}

interface ScenarioListItem {
  scenario: Scenario;
  has_result: boolean;
  summary: ScenarioSummary | null;
}

interface EdgeInfo {
  num_lanes: number;
  length_m: number;
  from: string;
  to: string;
  lanes: Array<{ id: string; index: number; length: number; speed: number }>;
}

export function ScenarioWorkspace() {
  const [types, setTypes] = useState<ScenarioTypeSpec[]>([]);
  const [defaultSeeds, setDefaultSeeds] = useState<number[]>([]);
  const [scenarios, setScenarios] = useState<ScenarioListItem[]>([]);
  const [edges, setEdges] = useState<Record<string, EdgeInfo>>({});
  
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  
  const [activeResult, setActiveResult] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const loadInitialData = useCallback(async () => {
    try {
      setLoading(true);
      const [typesRes, listRes, edgesRes] = await Promise.all([
        fetch(`${API()}/scenario/types`),
        fetch(`${API()}/scenario/list`),
        fetch(`${API()}/network/edges`),
      ]);
      
      const typesData = await typesRes.json();
      setTypes(typesData.types);
      setDefaultSeeds(typesData.seeds_default || [1, 2, 3]);

      const listData = await listRes.json();
      setScenarios(listData.scenarios);

      const edgesData = await edgesRes.json();
      setEdges(edgesData.edges ?? {});
      
      if (listData.scenarios.length > 0 && !selectedId) {
        setSelectedId(listData.scenarios[0].scenario.scenario_id);
      }
    } catch (e) {
      console.error(e);
      setErrorMsg(String(e));
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    loadInitialData();
  }, [loadInitialData]);

  const loadScenarioDetails = useCallback(async (id: string) => {
    if (id === "new") return;
    try {
      const res = await fetch(`${API()}/scenario/${id}`);
      if (res.ok) {
        const data = await res.json();
        setActiveResult(data.result);
      } else {
        setActiveResult(null);
      }
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    if (selectedId && !isCreating) {
      loadScenarioDetails(selectedId);
    }
  }, [selectedId, isCreating, loadScenarioDetails]);

  async function runScenario(id: string) {
    setRunning(true);
    setErrorMsg("");
    try {
      const res = await fetch(`${API()}/scenario/${id}/run`, {
        method: "POST"
      });
      if (!res.ok) {
        const detail = (await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`;
        throw new Error(detail);
      }
      await res.json();
      // Reload everything to get updated lists and results
      await loadInitialData();
      await loadScenarioDetails(id);
      setIsCreating(false);
    } catch (e) {
      setErrorMsg(String(e));
    } finally {
      setRunning(false);
    }
  }

  // --- Create Form State ---
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState("");
  const [newParams, setNewParams] = useState<Record<string, any>>({});
  
  function handleCreateClick() {
    setIsCreating(true);
    setSelectedId(null);
    setNewName("New Scenario");
    if (types.length > 0) {
      const initialType = types.find(t => t.type !== "baseline")?.type || types[0].type;
      handleTypeChange(initialType);
    }
  }

  function handleTypeChange(type: string) {
    setNewType(type);
    const spec = types.find(t => t.type === type);
    const initialParams: Record<string, any> = {};
    if (spec) {
      spec.params.forEach(p => {
        if (p.kind === "edge") {
          initialParams[p.name] = Object.keys(edges)[0] || "";
        } else if (p.kind === "lane") {
          initialParams[p.name] = 0;
        } else if (p.kind === "float" || p.kind === "int") {
          initialParams[p.name] = p.default ?? 0;
        } else {
          initialParams[p.name] = "";
        }
      });
    }
    setNewParams(initialParams);
  }

  async function submitCreate() {
    try {
      setErrorMsg("");
      const res = await fetch(`${API()}/scenario/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newName,
          type: newType,
          parameters: newParams,
          seeds: defaultSeeds
        })
      });
      if (!res.ok) {
        const detail = (await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`;
        throw new Error(detail);
      }
      const data = await res.json();
      await loadInitialData();
      setIsCreating(false);
      setSelectedId(data.scenario.scenario_id);
    } catch (e) {
      setErrorMsg(String(e));
    }
  }

  if (loading && scenarios.length === 0) return <div className="exp-shell"><p>Loading...</p></div>;

  const selectedItem = scenarios.find(s => s.scenario.scenario_id === selectedId);
  const selectedTypeSpec = types.find(t => t.type === (isCreating ? newType : selectedItem?.scenario.type));

  return (
    <div className="exp-shell">
      {/* ── Left Sidebar: List of Scenarios ── */}
      <aside className="exp-panel" style={{ flex: "0 0 320px", display: "flex", flexDirection: "column" }}>
        <h3 className="exp-section-title">Scenarios</h3>
        <button className="btn-ghost" onClick={handleCreateClick} style={{ marginBottom: 12 }}>
          + New Scenario
        </button>
        <div style={{ overflowY: "auto", flexGrow: 1, display: "flex", flexDirection: "column", gap: 8 }}>
          {scenarios.map(item => {
            const isSelected = selectedId === item.scenario.scenario_id && !isCreating;
            return (
              <div
                key={item.scenario.scenario_id}
                onClick={() => { setIsCreating(false); setSelectedId(item.scenario.scenario_id); }}
                style={{
                  padding: "10px",
                  borderRadius: "6px",
                  cursor: "pointer",
                  border: isSelected ? "1px solid var(--accent-base)" : "1px solid var(--gray-700)",
                  backgroundColor: isSelected ? "var(--gray-800)" : "transparent"
                }}
              >
                <div style={{ fontWeight: 600, display: "flex", justifyContent: "space-between" }}>
                  <span>{item.scenario.name}</span>
                  {item.scenario.scenario_id === "scn-baseline" && <span className="badge badge-online">BASE</span>}
                </div>
                <div style={{ fontSize: "0.85em", color: "var(--gray-400)" }}>{item.scenario.type}</div>
                {item.summary && (
                  <div style={{ fontSize: "0.85em", marginTop: 4, paddingTop: 4, borderTop: "1px solid var(--gray-800)" }}>
                    {item.summary.kind === "baseline" ? (
                      `TT: ${item.summary.baseline_travel_time_s?.toFixed(1)}s`
                    ) : (
                      <span style={{ color: item.summary.significant ? "var(--warning)" : "var(--gray-400)" }}>
                        ΔTT: {item.summary.travel_time_delta_pct! > 0 ? "+" : ""}{item.summary.travel_time_delta_pct?.toFixed(1)}%
                        {item.summary.significant ? " (Sig)" : " (No Sig)"}
                      </span>
                    )}
                  </div>
                )}
                {!item.has_result && <div style={{ fontSize: "0.85em", color: "var(--gray-500)", marginTop: 4 }}>Not run yet</div>}
              </div>
            );
          })}
        </div>
      </aside>

      {/* ── Right Panel: Details or Form ── */}
      <section className="exp-results" style={{ padding: "20px", display: "flex", flexDirection: "column" }}>
        {errorMsg && <div className="exp-error-card" style={{ marginBottom: 16 }}>{errorMsg}</div>}
        
        {isCreating ? (
          <div className="exp-result-card" style={{ maxWidth: 600 }}>
            <h3 style={{ marginTop: 0 }}>Create New Scenario</h3>
            <div className="exp-section">
              <label className="exp-label">Name</label>
              <input className="exp-input" value={newName} onChange={e => setNewName(e.target.value)} />

              <label className="exp-label" style={{ marginTop: 16 }}>Type</label>
              <select className="exp-select" value={newType} onChange={e => handleTypeChange(e.target.value)}>
                {types.filter(t => t.type !== "baseline").map(t => (
                  <option key={t.type} value={t.type}>{t.label}</option>
                ))}
              </select>
              {selectedTypeSpec?.help && <p className="exp-hint" style={{ marginTop: 4 }}>{selectedTypeSpec.help}</p>}

              {selectedTypeSpec?.params.map(p => (
                <div key={p.name} style={{ marginTop: 16 }}>
                  <label className="exp-label">{p.label} {p.help && <span className="exp-hint-inline">({p.help})</span>}</label>
                  {p.kind === "edge" && (
                    <select
                      className="exp-select"
                      value={newParams[p.name] || ""}
                      onChange={e => setNewParams({...newParams, [p.name]: e.target.value})}
                    >
                      {Object.entries(edges).map(([eid, info]) => (
                        <option key={eid} value={eid}>{eid} — {info.num_lanes} lanes, {info.length_m}m</option>
                      ))}
                    </select>
                  )}
                  {p.kind === "lane" && (() => {
                    const edgeId = newParams["edge_id"];
                    const lanesCount = edgeId && edges[edgeId] ? edges[edgeId].num_lanes : 1;
                    return (
                      <select
                        className="exp-select"
                        value={newParams[p.name] || 0}
                        onChange={e => setNewParams({...newParams, [p.name]: parseInt(e.target.value)})}
                      >
                        {Array.from({length: lanesCount}).map((_, idx) => (
                          <option key={idx} value={idx}>Lane {idx}</option>
                        ))}
                      </select>
                    );
                  })()}
                  {(p.kind === "float" || p.kind === "int") && (
                    <input
                      className="exp-input mono"
                      type="number"
                      step={p.step} min={p.min} max={p.max}
                      value={newParams[p.name] ?? ""}
                      onChange={e => setNewParams({...newParams, [p.name]: parseFloat(e.target.value)})}
                    />
                  )}
                </div>
              ))}
            </div>
            
            <div style={{ marginTop: 24, display: "flex", gap: 12 }}>
              <button className="btn-primary" onClick={submitCreate}>Create Scenario</button>
              <button className="btn-ghost" onClick={() => setIsCreating(false)}>Cancel</button>
            </div>
          </div>
        ) : selectedItem ? (
          <div className="exp-result-card">
            <h2 style={{ marginTop: 0, display: "flex", alignItems: "center", gap: 12 }}>
              {selectedItem.scenario.name}
              {selectedItem.scenario.scenario_id === "scn-baseline" && <span className="badge badge-online">BASE</span>}
            </h2>
            <div style={{ marginBottom: 16, color: "var(--gray-300)" }}>
              <strong>Type:</strong> {selectedItem.scenario.type}
              <br />
              {Object.keys(selectedItem.scenario.parameters).length > 0 && (
                <>
                  <strong>Parameters:</strong> {JSON.stringify(selectedItem.scenario.parameters)}
                </>
              )}
            </div>
            
            <div style={{ marginBottom: 24 }}>
              <button
                className="btn-confirm"
                onClick={() => runScenario(selectedItem.scenario.scenario_id)}
                disabled={running}
              >
                {running ? "⏳ Running..." : selectedItem.has_result ? "↺ Re-run Scenario" : "▶ Run Scenario"}
              </button>
            </div>

            {activeResult?.impact && (
              <div style={{ marginBottom: 24 }}>
                <h3 className="exp-section-title" style={{ marginTop: 0 }}>Impact Map</h3>
                <ImpactSummary impact={activeResult.impact} />
                <ImpactMap impact={activeResult.impact} />
              </div>
            )}
            {activeResult?.comparison && (
              <ResultTable
                comparison={activeResult.comparison}
              />
            )}
            {activeResult && !activeResult.comparison && activeResult.baseline && (
              <div className="exp-hint">Baseline scenario run successfully. No comparison (it is the baseline).</div>
            )}
            {selectedItem.scenario.scenario_id !== "scn-baseline" && (
              <>
                <InterventionPanel
                  scenarioId={selectedItem.scenario.scenario_id}
                  scenarioType={selectedItem.scenario.type}
                  hasResult={selectedItem.has_result}
                />
                <DecisionPanel
                  scenarioId={selectedItem.scenario.scenario_id}
                  scenarioType={selectedItem.scenario.type}
                  hasResult={selectedItem.has_result}
                />
              </>
            )}
            {!activeResult && !running && selectedItem.has_result && (
              <div className="exp-hint">Loading result...</div>
            )}
            {!selectedItem.has_result && !running && (
              <div className="exp-hint">Click Run to execute this scenario against the baseline.</div>
            )}
          </div>
        ) : (
          <div className="exp-idle-card">
            Select a scenario or create a new one.
          </div>
        )}
      </section>
    </div>
  );
}
