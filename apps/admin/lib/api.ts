// Thin client for the Cortex API. The admin UI is dev-mode (X-Tenant header);
// when CORTEX_AUTH_REQUIRED is on, set a bearer token here instead.

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TENANT_KEY = "cortex.tenant";

export function getTenant(): string {
  if (typeof window === "undefined") return "demo";
  return window.localStorage.getItem(TENANT_KEY) ?? "demo";
}

export function setTenant(tenant: string): void {
  window.localStorage.setItem(TENANT_KEY, tenant);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Tenant": getTenant(),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${detail ? `: ${detail}` : ""}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface Source {
  id: string;
  kind: string;
  status: string;
  created_at: string;
}

export interface ProcessSummary {
  id: string;
  name: string;
  status: string;
  version: number;
  freshness?: string;
}

export interface SearchHit {
  chunk_id: string;
  score: number;
  source_kind: string;
  text: string;
}

export const api = {
  listSources: () => request<{ sources: Source[] }>("/v1/sources"),
  createSource: (kind: string, config: Record<string, unknown> = {}) =>
    request<Source>("/v1/sources", { method: "POST", body: JSON.stringify({ kind, config }) }),
  syncSource: (id: string) =>
    request<Record<string, unknown>>(`/v1/sources/${id}/sync`, { method: "POST" }),
  uploadDocument: (id: string, external_id: string, content: string, kind = "doc") =>
    request<Record<string, unknown>>(`/v1/sources/${id}/documents`, {
      method: "POST",
      body: JSON.stringify({ external_id, content, kind }),
    }),
  deleteSource: (id: string) =>
    request<Record<string, unknown>>(`/v1/sources/${id}`, { method: "DELETE" }),
  listProcesses: () => request<{ processes: ProcessSummary[] }>("/v1/processes"),
  reviewProcess: (id: string, action: "approve" | "reject") =>
    request<Record<string, unknown>>(`/v1/processes/${id}/review`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),
  search: (q: string, k = 10) =>
    request<{ results: SearchHit[] }>("/v1/search", {
      method: "POST",
      body: JSON.stringify({ q, k }),
    }),
};
