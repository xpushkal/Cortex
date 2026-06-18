"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Source } from "@/lib/api";

export default function SourcesPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [kind, setKind] = useState("sample");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setSources((await api.listSources()).sources);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(true);
    setNote(null);
    try {
      await fn();
      setNote(label);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1>Sources</h1>

      <div className="card">
        <h2>Connect a source</h2>
        <div className="row">
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="sample">sample</option>
            <option value="github">github</option>
            <option value="file">file (upload)</option>
          </select>
          <button disabled={busy} onClick={() => void act("connected", () => api.createSource(kind))}>
            Connect
          </button>
          {note && <span className="ok">{note}</span>}
        </div>
      </div>

      {error && <p className="err">{error}</p>}

      <div className="card">
        <h2>Connected ({sources.length})</h2>
        {sources.length === 0 ? (
          <p className="muted">No sources yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Kind</th>
                <th>Status</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.id}>
                  <td>{s.kind}</td>
                  <td>
                    <span className="pill">{s.status}</span>
                  </td>
                  <td className="muted">{new Date(s.created_at).toLocaleString()}</td>
                  <td className="row">
                    <button
                      className="secondary"
                      disabled={busy || s.kind === "file"}
                      title={s.kind === "file" ? "file sources take uploads, not sync" : ""}
                      onClick={() => void act("synced", () => api.syncSource(s.id))}
                    >
                      Sync
                    </button>
                    <button
                      className="danger"
                      disabled={busy}
                      onClick={() => void act("disconnected", () => api.deleteSource(s.id))}
                    >
                      Disconnect
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
