# Cortex Admin UI

A minimal Next.js (App Router) operator surface over the Cortex API:

- **Sources** — connect, sync, upload documents, and disconnect sources (`/v1/sources`).
- **Processes** — review the extracted process registry; approve/reject (`/v1/processes`).
- **Search** — grounded retrieval against a tenant's index (`/v1/search`).

The product is API-first; this UI is optional and stateless (it only calls the API).
It is intentionally **excluded** from the uv (Python) workspace.

## Run

```bash
cd apps/admin
npm install
npm run dev            # http://localhost:3001
```

Point it at the API with `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).
Pick a tenant in the top-right (dev mode trusts `X-Tenant`; when
`CORTEX_AUTH_REQUIRED` is on, wire a bearer token in `lib/api.ts`).

```bash
npm run build          # production build / typecheck
npm run typecheck      # tsc --noEmit
```
