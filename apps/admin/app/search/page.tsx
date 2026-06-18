"use client";

import { useState } from "react";
import { api, type SearchHit } from "@/lib/api";

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [searched, setSearched] = useState(false);

  async function run() {
    if (!q.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setHits((await api.search(q, 10)).results);
      setSearched(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1>Search</h1>
      <div className="card">
        <div className="row">
          <input
            aria-label="query"
            placeholder="e.g. refund approval over $500"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void run()}
            style={{ flex: 1, minWidth: 280 }}
          />
          <button disabled={busy} onClick={() => void run()}>
            Search
          </button>
        </div>
      </div>

      {error && <p className="err">{error}</p>}

      {searched && hits.length === 0 && !error && <p className="muted">No results.</p>}

      {hits.map((h) => (
        <div className="card" key={h.chunk_id}>
          <div className="row">
            <span className="pill">{h.source_kind}</span>
            <span className="score">score {h.score.toFixed(3)}</span>
          </div>
          <p>{h.text}</p>
        </div>
      ))}
    </div>
  );
}
