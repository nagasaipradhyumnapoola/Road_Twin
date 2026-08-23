import { useCallback, useEffect, useState } from "react";

const API = () =>
  `http://127.0.0.1:${(window as unknown as { __rtPort?: number }).__rtPort ?? 8765}`;

interface ObjectiveSpec {
  objective: string;
  label: string;
  unit: string;
  help: string;
}
interface OptionRow {
  intervention_id: string;
  name: string;
  type: string;
  improvement_pct: number | null;
  meets_goal: boolean;
  within_budget: boolean;
}
interface GoalResult {
  objective_label: string;
  achieved: boolean;
  best_result_pct: number | null;
  best_tested_option: { name: string; improvement_pct: number } | null;
  options: OptionRow[];
  message: string;
  note: string;
}
interface DecisionCard {
  location: { name: string; critical_junction: string | null };
  scenario: { name: string; type: string };
  impact: {
    travel_time_pct: number | null;
    queue_pct: number | null;
    affected_roads: number | null;
    critical_junctions: number | null;
  };
  objective_label: string;
  goal: { target_pct: number };
  achieved: boolean;
  best_tested_option: {
    name: string;
    result: { travel_time_pct: number | null; queue_pct: number | null; completed_pct: number | null };
  } | null;
  message: string;
  simulation: { seeds: number };
  assumptions: string[];
  limitations: string[];
}

const signed = (v: number | null | undefined, unit = "%") =>
  v === null || v === undefined ? "N/A" : `${v > 0 ? "+" : ""}${v.toFixed(1)}${unit}`;

/**
 * P14 — "Engineer Goal → Decision": the engineer states a measurable goal; the
 * search measures the P13 tested options against it (running them with real
 * SUMO first if needed) and produces the decision card. Honest about failure —
 * it reports the best result reached when nothing clears the target, and never
 * forces a recommendation.
 */
export function DecisionPanel({
  scenarioId,
  scenarioType,
  hasResult,
}: {
  scenarioId: string;
  scenarioType: string;
  hasResult: boolean;
}) {
  const [objectives, setObjectives] = useState<ObjectiveSpec[]>([]);
  const [objective, setObjective] = useState("reduce_travel_time");
  const [targetPct, setTargetPct] = useState(20);
  const [maxInterventions, setMaxInterventions] = useState(1);

  const [goalResult, setGoalResult] = useState<GoalResult | null>(null);
  const [card, setCard] = useState<DecisionCard | null>(null);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportMsg, setExportMsg] = useState("");
  const [err, setErr] = useState("");

  const isClosure = scenarioType === "lane_closure" || scenarioType === "road_closure";

  const loadMeta = useCallback(async () => {
    setGoalResult(null);
    setCard(null);
    setErr("");
    setExportMsg("");
    if (!isClosure) return;
    try {
      const o = await fetch(`${API()}/decision/objectives`);
      if (o.ok) {
        const data = await o.json();
        setObjectives(data.objectives ?? []);
        setTargetPct(data.default_target_pct ?? 20);
        setMaxInterventions(data.default_max_interventions ?? 1);
      }
      const d = await fetch(`${API()}/scenario/${scenarioId}/decision`);
      if (d.ok) setCard(await d.json());
    } catch {
      /* none yet */
    }
  }, [scenarioId, isClosure]);

  useEffect(() => {
    loadMeta();
  }, [loadMeta]);

  async function findSolutions() {
    setBusy(true);
    setErr("");
    setExportMsg("");
    try {
      const r = await fetch(`${API()}/scenario/${scenarioId}/goal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          objective,
          target_pct: targetPct,
          max_interventions: maxInterventions,
        }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`);
      const data = await r.json();
      setGoalResult(data.goal_result);
      setCard(data.decision_card);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function exportReport() {
    setExporting(true);
    setExportMsg("");
    setErr("");
    try {
      const r = await fetch(`${API()}/scenario/${scenarioId}/decision/export`, { method: "POST" });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`);
      const data = await r.json();
      setExportMsg(`Exported: ${data.zip_path} (${data.size_kb} KB)`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setExporting(false);
    }
  }

  if (!isClosure) return null;

  return (
    <div style={{ marginTop: 24, borderTop: "1px solid var(--gray-800)", paddingTop: 16 }}>
      <h3 className="exp-section-title" style={{ marginTop: 0 }}>Engineering Goal</h3>

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "flex-end" }}>
        <div>
          <label className="exp-label">Objective</label>
          <select className="exp-select" value={objective} onChange={(e) => setObjective(e.target.value)}>
            {objectives.map((o) => (
              <option key={o.objective} value={o.objective}>{o.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="exp-label">Target improvement</label>
          <input
            className="exp-input mono"
            type="number"
            min={1}
            max={100}
            step={1}
            value={targetPct}
            onChange={(e) => setTargetPct(parseFloat(e.target.value))}
            style={{ width: 90 }}
          />
        </div>
        <div>
          <label className="exp-label">Max interventions</label>
          <input
            className="exp-input mono"
            type="number"
            min={1}
            max={8}
            step={1}
            value={maxInterventions}
            onChange={(e) => setMaxInterventions(parseInt(e.target.value))}
            style={{ width: 90 }}
          />
        </div>
        <button className="btn-primary" onClick={findSolutions} disabled={busy || !hasResult}>
          {busy ? "⏳ Searching (real SUMO)…" : "🎯 Find Solutions"}
        </button>
      </div>
      {!hasResult && <p className="exp-hint" style={{ marginTop: 6 }}>Run the scenario first.</p>}
      {err && <p className="exp-hint err" style={{ marginTop: 6 }}>{err}</p>}

      {goalResult && (
        <div
          style={{
            marginTop: 16,
            padding: "12px 16px",
            borderRadius: 8,
            background: goalResult.achieved ? "rgba(34,197,94,0.12)" : "var(--gray-800)",
            border: goalResult.achieved ? "1px solid #22c55e" : "1px solid var(--gray-700)",
          }}
        >
          <div style={{ fontSize: "0.8em", color: "var(--gray-400)" }}>
            {goalResult.achieved ? "TARGET ACHIEVED ✓" : "TARGET NOT ACHIEVED"}
          </div>
          <div style={{ marginTop: 4 }}>{goalResult.message}</div>
        </div>
      )}

      {goalResult && goalResult.options.length > 0 && (
        <table style={{ width: "100%", marginTop: 16, borderCollapse: "collapse", fontSize: "0.9em" }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--gray-400)" }}>
              <th style={{ padding: "6px 8px" }}>Tested option</th>
              <th style={{ padding: "6px 8px" }}>{goalResult.objective_label}</th>
              <th style={{ padding: "6px 8px" }}>Meets goal</th>
            </tr>
          </thead>
          <tbody>
            {goalResult.options.map((o) => (
              <tr
                key={o.intervention_id}
                style={{ borderTop: "1px solid var(--gray-800)", background: o.meets_goal ? "rgba(34,197,94,0.08)" : undefined }}
              >
                <td style={{ padding: "6px 8px", fontWeight: o.meets_goal ? 700 : 400 }}>
                  {o.meets_goal ? "★ " : ""}{o.name}
                </td>
                <td style={{ padding: "6px 8px", color: (o.improvement_pct ?? 0) > 0 ? "#22c55e" : "var(--gray-400)" }}>
                  {signed(o.improvement_pct)}
                </td>
                <td style={{ padding: "6px 8px", color: o.meets_goal ? "#22c55e" : "var(--gray-400)" }}>
                  {o.improvement_pct === null ? "no result" : o.meets_goal ? "yes" : "no"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {card && <DecisionCardView card={card} />}

      {card && (
        <div style={{ marginTop: 16 }}>
          <button className="btn-confirm" onClick={exportReport} disabled={exporting}>
            {exporting ? "⏳ Exporting…" : "⬇ Export Report"}
          </button>
          {exportMsg && <p className="exp-hint" style={{ marginTop: 6 }}>{exportMsg}</p>}
        </div>
      )}

      {goalResult && <p className="exp-hint" style={{ marginTop: 8 }}>{goalResult.note}</p>}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "3px 0" }}>
      <span style={{ color: "var(--gray-400)" }}>{label}</span>
      <span style={{ fontWeight: 600 }}>{value}</span>
    </div>
  );
}

function DecisionCardView({ card }: { card: DecisionCard }) {
  const best = card.best_tested_option;
  return (
    <div
      className="exp-result-card"
      style={{ marginTop: 20, borderTop: "2px solid var(--accent-base)", maxWidth: 520 }}
    >
      <div style={{ textAlign: "center", letterSpacing: 2, fontWeight: 700, color: "var(--gray-300)" }}>
        ROADTWIN DECISION
      </div>

      <h4 style={{ marginBottom: 4 }}>Location</h4>
      <div style={{ color: "var(--gray-300)" }}>
        {card.location.name}
        {card.location.critical_junction ? ` / Junction ${card.location.critical_junction}` : ""}
      </div>

      <h4 style={{ marginBottom: 4 }}>Scenario</h4>
      <div style={{ color: "var(--gray-300)" }}>{card.scenario.name} ({card.scenario.type})</div>

      <h4 style={{ marginBottom: 4 }}>Impact</h4>
      <Row label="Travel Time" value={signed(card.impact.travel_time_pct)} />
      <Row label="Queue" value={signed(card.impact.queue_pct)} />
      <Row label="Affected Roads" value={String(card.impact.affected_roads ?? "n/a")} />

      <h4 style={{ marginBottom: 4 }}>Best Tested Option</h4>
      {best ? (
        <>
          <div style={{ fontWeight: 700 }}>{best.name}</div>
          <Row label="Travel Time" value={signed(best.result.travel_time_pct)} />
          <Row label="Queue" value={signed(best.result.queue_pct)} />
          <Row label="Completed" value={signed(best.result.completed_pct)} />
        </>
      ) : (
        <div style={{ color: "var(--gray-400)" }}>None — no tested option satisfied the goal.</div>
      )}

      <h4 style={{ marginBottom: 4 }}>Simulation</h4>
      <div style={{ color: "var(--gray-300)" }}>{card.simulation.seeds} seeds</div>

      <h4 style={{ marginBottom: 4 }}>Assumptions</h4>
      {card.assumptions.map((a, i) => (
        <div key={i} style={{ color: "var(--gray-400)", fontSize: "0.9em" }}>{a}</div>
      ))}

      <h4 style={{ marginBottom: 4 }}>Limitations</h4>
      {card.limitations.map((l, i) => (
        <div key={i} style={{ color: "var(--gray-400)", fontSize: "0.9em" }}>{l}</div>
      ))}
    </div>
  );
}
