## What & why

<!-- One paragraph: what this changes and the problem it solves. -->

## Milestone gate

<!-- Which ROADMAP gate does this advance, if any? e.g. "M1: wires the eval gate". -->
Advances: M_ / none

## Definition of Done

- [ ] Conventional Commit title (`feat:`, `fix:`, `chore:`, `docs:`, `ci:`, `test:`, …)
- [ ] `just ci` green locally (ruff + mypy + tests)
- [ ] Tests added/updated for the change (unit; integration if it touches I/O)
- [ ] No secrets committed; `.env.example` updated if new config was added
- [ ] Docs/CHANGELOG updated if behavior or interfaces changed
- [ ] Tenant isolation preserved (no query path without a tenant filter)
- [ ] Every new knowledge/process artifact carries citations

## Notes for the reviewer

<!-- Risks, follow-ups, anything deliberately out of scope. -->
