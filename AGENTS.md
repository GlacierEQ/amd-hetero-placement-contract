# AGENTS.md — amd-hetero-placement-contract

**Company:** Amd
**Domain:** Cloud AI Platform Engineering

## Quick Rules
- **Test command:** `PYTHONPATH=src pytest tests/ -v`
- **Lint:** `ruff check src/ tests/`
- **No drive-by edits** — load the skill first.

## Architecture
- `src/amd_hetero_placement_contract/core.py` — Domain logic (Cloud AI Platform Engineering)
- `src/hetero_placement_contract.py` — Deterministic placement engine + CLI
- `src/impact_assurance.py` — Impact assurance scoring
- `tests/` — Verified test suite (29 tests)
- `.github/workflows/ci.yml` — Enforced CI pipeline

## Epistemology
- L0 (Presence): verified — package importable, CLI resolves.
- L1 (Structure): verified — public classes/functions instantiate with documented signatures.
- L2 (Behavior): verified — 29 tests pass; ruff clean (0 errors); demo runs.
- Aspirational (L0/L1 only): real AMD hardware benchmarks, live telemetry providers, hosted service/deployment, vendor affiliation. Not claimed.
