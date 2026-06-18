import Link from "next/link";

export default function Home() {
  return (
    <div>
      <h1>Cortex Admin</h1>
      <div className="card">
        <p className="muted">
          A minimal operator surface over the Cortex API. Pick a tenant in the top-right,
          then:
        </p>
        <ul>
          <li>
            <Link href="/sources">Sources</Link> — connect, sync, upload documents, and
            disconnect knowledge sources.
          </li>
          <li>
            <Link href="/processes">Processes</Link> — review the extracted process registry
            (approve / reject drafts and stale items).
          </li>
          <li>
            <Link href="/search">Search</Link> — run grounded retrieval against the tenant&apos;s
            index.
          </li>
        </ul>
        <p className="muted">
          API base is <code>NEXT_PUBLIC_API_URL</code> (default{" "}
          <code>http://localhost:8000</code>).
        </p>
      </div>
    </div>
  );
}
