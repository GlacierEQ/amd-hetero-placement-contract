# Heterogeneous Workload Placement Engine

Independent GlacierEQ portfolio implementation aligned to public AMD operating themes. This repository is not affiliated with or endorsed by AMD.

## Purpose

Given a workload and a caller-supplied heterogeneous topology, select the strongest feasible execution target or refuse placement with concrete reasons.

The engine treats placement as an outcome problem rather than a policy gate. It evaluates:

- device type
- available compute after current utilization
- available memory rather than nominal capacity
- bandwidth
- latency ceiling
- privacy level
- optional power cap
- locality preference
- energy-efficiency proxy

Hard constraints eliminate targets. Remaining candidates are deterministically ranked with transparent score components and stable tie-breaking.

## Run it

```bash
python scripts/operate.py
```

The default command executes a complete built-in workload/topology example and prints the placement receipt.

To use your own topology:

```bash
python scripts/operate.py --input request.json --output placement.json
```

Example request:

```json
{
  "subject_id": "inference-batch-42",
  "budget": 1.0,
  "payload": {
    "workload": {
      "compute_tflops": 20,
      "memory_gb": 16,
      "bandwidth_gbps": 25,
      "max_latency_ms": 15,
      "device": "gpu",
      "privacy": "trusted",
      "locality": "rack-a"
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
        "locality": "rack-a"
      }
    ]
  }
}
```

## Output

A successful receipt contains:

- selected target
- deterministic score
- ranked feasible candidates
- rejected targets and rejection reasons
- available compute and memory observations
- deterministic SHA-256 receipt digest

A workload with no feasible target returns `REFUSE` and exit code `2` from the CLI.

## Verify behavior

```bash
python -m pytest -q
```

Tests cover feasible selection, no-feasible-target refusal, privacy, power caps, utilization pressure, available-memory pressure, device mismatch, deterministic ordering, duplicate identities, latency boundaries, and malformed requests.

## Design boundary

This implementation uses caller-supplied measurements. It is a reproducible placement algorithm, not a benchmark claim about real AMD hardware. The mechanism can later be connected to live telemetry without changing the placement contract.
