import { useCallback, useEffect, useState } from "react";

const API = () =>
  `http://127.0.0.1:${(window as unknown as { __rtPort?: number }).__rtPort ?? 8765}`;

interface Deltas {
  travel_time_s: number | null;
  travel_time_pct: number | null;
  queue_m: number | null;
  completed_vehicles: number | null;
}
interface Arm {
  avg_travel_time_s: number | null;
  mean_queue_length_m: number | null;
  completed_vehicles: number | null;
}
interface InterventionResult {
  intervention_id: string;
  type: string;
  name: string;
  status: "evaluated" | "failed";
  baseline?: Arm;
  intervention?: Arm;
  deltas?: Deltas;
  significant?: boolean;
  failure_reason?: string;
}
interface Ranking {
  ranked: string[];
  best_tested_option: { intervention_id: string; name: string; deltas: Deltas } | null;
  improves: boolean;
  message: string;
  note: string;
}
interface Payload {
  scenario_id: string;
  seeds: number[];
  candidates: Array<{ intervention_id: string; name: string; type: string; validation_state: string; failure_reason?: string }>;
  results: InterventionResult[];
  ranking: Ranking | null;
}

const num = (v: number | null | undefined, unit = "", digits = 1) =>
  v === null || v === undefined ? "N/A" : `${v.toFixed(digits)}${unit}`;
const signed = (v: number | null | undefined, unit = "") =>
  v === null || v === undefined ? "N/A" : `${v > 0 ? "+" : ""}${v.toFixed(1)}${unit}`;

/**
 * P13 — "Find Better Options": generate candidate interventions for a closure
 * scenario, evaluate them with real SUMO, and show the tested options + the best
 * tested option. All numbers come from the persisted intervention results.
 */
export function InterventionPanel({
  scenarioId,
  scenarioType,
  hasResult,
}: {
  scenarioId: string;
  scenarioType: string;
  hasResult: boolean;
}) {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const isClosure = scenarioType === "lane_closure" || scenarioType === "road_closure";

  const loadExisting = useCallback(async () => {
    setPayload(null);
    setErr("");
    if (!isClosure) return;
    try {
      const r = await fetch(`${API()}/scenario/${scenarioId}/interventions`);
      if (r.ok) setPayload(await r.json());
    } catch {
      /* none yet */
    }
  }, [scenarioId, isClosure]);

  useEffect(() => {
    loadExisting();
  }, [loadExisting]);

  async function findBetter() {
    setBusy(true);
    setErr("");
    try {
      const g = await fetch(`${API()}/scenario/${scenarioId}/interventions`, { method: "POST" });
      if (!g.ok) throw new Error((await g.json().catch(() => ({}))).detail ?? `HTTP ${g.status}`);
      const r = await fetch(`${API()}/scenario/${scenarioId}/interventions/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`);
      setPayload(await r.json());
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!isClosure) return null;

  const ranking = payload?.ranking ?? null;
  const bestId = ranking?.best_tested_option?.intervention_id;

  return (
    <div style={{ marginTop: 24, borderTop: "1px solid var(--gray-800)", paddingTop: 16 }}>
      <h3 className="exp-section-title" style={{ marginTop: 0 }}>Interventions</h3>
      <button className="btn-primary" onClick={findBetter} disabled={busy || !hasResult}>
        {busy ? "⏳ Testing options (real SUMO)…" : "🔧 Find Better Options"}
      </button>
      {!hasResult && <p className="exp-hint" style={{ marginTop: 6 }}>Run the scenario first.</p>}
      {err && <p className="exp-hint err" style={{ marginTop: 6 }}>{err}</p>}

      {ranking && (
        <div
          style={{
            marginTop: 16,
            padding: "12px 16px",
            borderRadius: 8,
            background: ranking.improves ? "rgba(34,197,94,0.12)" : "var(--gray-800)",
            border: ranking.improves ? "1px solid #22c55e" : "1px solid var(--gray-700)",
          }}
        >
          <div style={{ fontSize: "0.8em", color: "var(--gray-400)" }}>BEST TESTED OPTION</div>
          <div style={{ fontSize: "1.2em", fontWeight: 700 }}>
            {ranking.best_tested_option ? ranking.best_tested_option.name : "—"}
          </div>
          <div style={{ marginTop: 4 }}>{ranking.message}</div>
          {ranking.best_tested_option && (
            <div style={{ marginTop: 6, fontSize: "0.9em", color: "var(--gray-300)" }}>
              Travel time {signed(ranking.best_tested_option.deltas.travel_time_s, "s")} (
              {signed(ranking.best_tested_option.deltas.travel_time_pct, "%")}) · Queue{" "}
              {signed(ranking.best_tested_option.deltas.queue_m, "m")}
            </div>
          )}
        </div>
      )}

      {payload && payload.results.length > 0 && (
        <table style={{ width: "100%", marginTop: 16, borderCollapse: "collapse", fontSize: "0.9em" }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--gray-400)" }}>
              <th style={{ padding: "6px 8px" }}>Candidate</th>
              <th style={{ padding: "6px 8px" }}>Status</th>
              <th style={{ padding: "6px 8px" }}>Travel Time</th>
              <th style={{ padding: "6px 8px" }}>Queue</th>
              <th style={{ padding: "6px 8px" }}>Result</th>
            </tr>
          </thead>
          <tbody>
            {payload.results.map((r) => {
              const best = r.intervention_id === bestId;
              return (
                <tr
                  key={r.intervention_id}
                  style={{ borderTop: "1px solid var(--gray-800)", background: best ? "rgba(34,197,94,0.08)" : undefined }}
                >
                  <td style={{ padding: "6px 8px", fontWeight: best ? 700 : 400 }}>
                    {best ? "★ " : ""}{r.name}
                  </td>
                  <td style={{ padding: "6px 8px" }}>
                    {r.status === "failed" ? (
                      <span style={{ color: "var(--danger, #ef4444)" }}>FAILED</span>
                    ) : (
                      <span style={{ color: "var(--gray-300)" }}>tested{r.significant ? " · sig" : ""}</span>
                    )}
                  </td>
                  {r.status === "evaluated" ? (
                    <>
                      <td style={{ padding: "6px 8px" }}>
                        {num(r.baseline?.avg_travel_time_s, "s")} → {num(r.intervention?.avg_travel_time_s, "s")}
                        <span style={{ color: (r.deltas?.travel_time_s ?? 0) < 0 ? "#22c55e" : "var(--gray-400)", marginLeft: 6 }}>
                          ({signed(r.deltas?.travel_time_s, "s")})
                        </span>
                      </td>
                      <td style={{ padding: "6px 8px" }}>
                        {num(r.baseline?.mean_queue_length_m, "m")} → {num(r.intervention?.mean_queue_length_m, "m")}
                      </td>
                      <td style={{ padding: "6px 8px", color: (r.deltas?.travel_time_s ?? 0) < 0 ? "#22c55e" : "var(--gray-400)" }}>
                        {(r.deltas?.travel_time_s ?? 0) < 0 ? "improves" : "no improvement"}
                      </td>
                    </>
                  ) : (
                    <td colSpan={3} style={{ padding: "6px 8px", color: "var(--gray-400)" }}>
                      <strong style={{ color: "var(--danger, #ef4444)" }}>Reason:</strong> {r.failure_reason}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {ranking && <p className="exp-hint" style={{ marginTop: 8 }}>{ranking.note}</p>}
    </div>
  );
}
