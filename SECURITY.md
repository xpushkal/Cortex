# Security Policy

## Reporting a vulnerability

Email the maintainer (see the GitHub profile for `@xpushkal`) with details and a
repro. Please do **not** open a public issue for security reports. Expect an
acknowledgement within a few days. Coordinated disclosure is appreciated.

## Secrets handling

- No secrets in the repository, ever. `.env` is git-ignored; `.env.example` is the
  template of required variables.
- `gitleaks` runs in pre-commit and in CI to catch accidental commits.
- In cloud environments, secrets are injected from the platform secret store
  (M4 Terraform/k8s), never baked into images.

## Product security invariants

These are enforced in code and asserted in tests — a regression fails the build:

- **Tenant isolation.** Vector queries require a mandatory tenant filter
  (rejected otherwise); relational access is tenant-scoped (RLS + app guard). A
  CI test seeds two tenants and asserts zero cross-tenant results.
- **Provenance.** Every served fact, answer, and process step links to its source
  chunk; uncited process steps are rejected at validation time.
- **Auth.** API access is per-tenant bearer tokens; a token whose tenant ≠
  `X-Tenant` is rejected `403` (see `docs/API.md`).
- **Rate limiting.** Per-tenant (ingress) and per-source (egress) token buckets
  bound abuse and protect source API quotas.

## Dependencies

Dependabot proposes weekly updates; `pip-audit` runs in CI to flag known
vulnerabilities in the locked dependency set.
