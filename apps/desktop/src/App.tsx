/* RoadTwin Phase 1 — skeleton UI
 * Shows sidecar status from the Tauri event bus.
 * No product features. One round-trip only.
 */
import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import "./App.css";

type SidecarStatus =
  | { kind: "booting" }
  | { kind: "ready"; port: number; health: Record<string, unknown> }
  | { kind: "error"; message: string };

async function fetchHealth(port: number): Promise<Record<string, unknown>> {
  const r = await fetch(`http://127.0.0.1:${port}/health`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export default function App() {
  const [status, setStatus] = useState<SidecarStatus>({ kind: "booting" });

  useEffect(() => {
    const unlistenReady = listen<number>("sidecar-ready", async ({ payload: port }) => {
      try {
        const health = await fetchHealth(port);
        setStatus({ kind: "ready", port, health });
      } catch (e) {
        setStatus({ kind: "error", message: String(e) });
      }
    });

    const unlistenError = listen<string>("sidecar-error", ({ payload: message }) => {
      setStatus({ kind: "error", message });
    });

    return () => {
      unlistenReady.then((f) => f());
      unlistenError.then((f) => f());
    };
  }, []);

  return (
    <div className="shell">
      <header className="topbar">
        <span className="logo">RoadTwin</span>
        <span className="tagline">Digital Road Twin</span>
        <StatusBadge status={status} />
      </header>

      <main className="stage">
        {status.kind === "booting" && (
          <div className="status-card booting">
            <div className="spinner" />
            <p>Starting core engine…</p>
          </div>
        )}
        {status.kind === "ready" && (
          <div className="status-card ready">
            <div className="check">✓</div>
            <h2>Core engine online</h2>
            <pre className="json-dump">
              {JSON.stringify(status.health, null, 2)}
            </pre>
            <p className="hint">Port {status.port} · Phase 1 skeleton verified</p>
          </div>
        )}
        {status.kind === "error" && (
          <div className="status-card error">
            <div className="icon-err">✗</div>
            <h2>Sidecar error</h2>
            <pre className="error-msg">{status.message}</pre>
          </div>
        )}
      </main>
    </div>
  );
}

function StatusBadge({ status }: { status: SidecarStatus }) {
  const map = {
    booting: { label: "STARTING", cls: "badge-starting" },
    ready: { label: "ONLINE", cls: "badge-online" },
    error: { label: "ERROR", cls: "badge-error" },
  } as const;
  const { label, cls } = map[status.kind];
  return <span className={`badge ${cls}`}>{label}</span>;
}
