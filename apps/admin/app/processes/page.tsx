"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type ProcessSummary } from "@/lib/api";

export default function ProcessesPage() {
  const [processes, setProcesses] = useState<ProcessSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setProcesses((await api.listProcesses()).processes);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function review(id: string, action: "approve" | "reject") {
    setBusy(true);
    try {
      await api.reviewProcess(id, action);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1>Processes</h1>
      {error && <p className="err">{error}</p>}
      <div className="card">
        <h2>Registry ({processes.length})</h2>
        {processes.length === 0 ? (
          <p className="muted">No processes extracted yet — connect and sync a source.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Version</th>
                <th>Freshness</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {processes.map((p) => (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td>
                    <span className="pill">{p.status}</span>
                  </td>
                  <td className="muted">v{p.version}</td>
                  <td className="muted">{p.freshness ?? "—"}</td>
                  <td className="row">
                    <button
                      className="secondary"
                      disabled={busy || p.status === "active"}
                      onClick={() => void review(p.id, "approve")}
                    >
                      Approve
                    </button>
                    <button
                      className="danger"
                      disabled={busy || p.status === "deprecated"}
                      onClick={() => void review(p.id, "reject")}
                    >
                      Reject
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
