# Heterogeneous Placement Contract

Independent GlacierEQ portfolio exhibit aligned to **AMD** operating themes.

> **Not affiliated.** This repository is not affiliated with, endorsed by, employed by, or deployed at AMD.
> No proprietary access, production deployment, customer impact, or company partnership is claimed.

## Bottleneck (GlacierEQ hypothesis)

Data movement, network synchronization, memory hierarchy, and software integration.

**Brick wall:** Supporting synchronized training, low-latency inference, and persistent agent workloads without utilization or power collapse.

**Observed public pressure (snapshot hypothesis):** AI workloads require coordinated CPU, GPU, networking, memory, and open software across training and inference.

## Innovation mechanism

**Heterogeneous Placement Contract** — Expose a placement descriptor (latency, energy, memory locality, privacy) and a deterministic placer that returns a bound execution target or explicit refusal.

## Target roles

- Applied AI Systems Architect
- Forward-Deployed Engineer
- AI Infrastructure / Governance Engineer

## Application move

Present a vendor-neutral workload and topology analysis rather than brand-specific claims.

## Current scaffold state

This leaf is a **scaffold**: contracts, tests, and a stub mechanism exist so another engineer/AI can fill production-grade code without inventing company affiliation.

| Surface | Path |
|---------|------|
| Mechanism stub | `src/hetero_placement_contract.py` |
| Operate entry | `scripts/operate.py` |
| Contract tests | `tests/` |
| Target contract | `machine/target-contract.json` |
| **AI fill-in brief** | **`DEV_UP_INSTRUCTIONS.md`** |
| Issue contract | `ISSUE_CONTRACT.md` |

## Non-claims

- No AMD employment, endorsement, proprietary data, or production use
- No customer, revenue, latency, or scale claims without separate receipts
- Scaffold tests define **intended behavior**, not verified production excellence

## Next gate

Create reproducible performance tests on available hardware or clearly simulated models.
