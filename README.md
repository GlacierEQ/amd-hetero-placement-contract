# Heterogeneous Workload Placement Engine

Independent GlacierEQ portfolio implementation aligned to public heterogeneous-compute operating themes. This repository is not affiliated with or endorsed by AMD.

## Purpose

Given a workload and a caller-supplied heterogeneous topology, select the strongest feasible execution target or refuse placement with concrete reasons.

The engine treats placement as an outcome problem rather than a policy gate. Hard constraints eliminate targets that cannot actually execute the workload; feasible targets are then ranked deterministically.

## Feasibility model

The placement engine evaluates:

- device type
- available compute after current utilization
- available memory rather than nominal capacity
- bandwidth
- latency ceiling
- privacy level
- optional power cap
- target availability
- required execution features
- hourly cost against the request budget
- optional grant expiry

A target that violates any hard requirement is rejected with explicit reasons.

## Ranking model

Feasible targets are scored with transparent components for:

- latency margin
- compute headroom
- memory headroom
- bandwidth headroom
- energy-efficiency proxy
- locality preference
- cost headroom

Ties are resolved by target id, so equivalent inputs remain deterministic.

## Install

```bash
python -m pip install -e .
```

The package exposes:

```bash
hetero-place
```

## Run it

The repository retains a concrete demo:

```bash
python scripts/operate.py
```

The installed CLI accepts JSON from a file or stdin and can persist the receipt:

```bash
hetero-place --input request.json --output placement.json --pretty
```

or:

```bash
cat request.json | hetero-place --pretty
```

Example request:

```json
{
  "subject_id": "inference-batch-42",
  "budget": 1.0,
  "grant_id": "placement-window-1",
  "not_after": 2000.0,
  "now": 1000.0,
  "workload": {
    "compute_tflops": 20,
    "memory_gb": 16,
    "bandwidth_gbps": 25,
    "max_latency_ms": 15,
    "device": "gpu",
    "privacy": "trusted",
    "locality": "rack-a",
    "required_features": ["fp16"]
  },
  "targets": [
    {
      "id": "node-a",
      "device": "gpu",
      "compute_tflops": 80,
      "memory_gb": 64,
      "available_memory_gb": 48,
      "bandwidth_gbps": 100,
      "latency_ms": 3,
      "power_watts": 260,
      "utilization": 0.20,
      "privacy": "trusted",
      "locality": "rack-a",
      "cost_per_hour": 0.50,
      "available": true,
      "features": ["fp16", "bf16"]
    }
  ]
}
```

For backward compatibility, callers may also place `workload` and `targets` under a `payload` object.

## Output

A successful receipt contains:

- selected target
- selected hourly cost
- deterministic score
- ranked feasible candidates
- per-component score details
- rejected targets and rejection reasons
- available compute and memory observations
- deterministic SHA-256 receipt digest

A workload with no feasible target returns `REFUSE` and process exit code `2` from the installed CLI.

## Verify behavior

```bash
python -m pytest -q
python scripts/operate.py
```

CI also installs the package and executes `hetero-place` against a real request.

Tests cover feasible selection, no-feasible-target refusal, privacy, power caps, utilization pressure, available-memory pressure, device mismatch, deterministic ordering, duplicate identities, latency boundaries, malformed requests, real budget enforcement, cost-sensitive ranking, availability, required features, grant expiry, and installed CLI execution.

## Design boundary

This implementation uses caller-supplied measurements. It is a reproducible placement algorithm, not a benchmark claim about real AMD hardware. Live telemetry providers can be connected later without changing the placement decision contract.

## Status

**FUNCTIONAL** as a standalone deterministic placement engine, Python module, demo, and installed CLI.

Deployment is not intrinsic to this repository because it is a reusable placement component rather than a hosted service. A service wrapper would be a separate runtime surface if one becomes operationally useful.
