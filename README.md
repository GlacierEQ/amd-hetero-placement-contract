# Heterogeneous Placement Contract

A deterministic, vendor-neutral workload placement engine for heterogeneous compute targets.

> **Independent portfolio project.** This repository is not affiliated with, endorsed by, employed by, or deployed at AMD. No proprietary AMD access, customer impact, production deployment, or partnership is claimed.

## Purpose

Given a workload and a set of CPU/GPU/APU/NPU or other execution targets, select the strongest feasible target or explicitly refuse placement.

The engine treats feasibility and ranking as separate problems:

1. **Hard constraints** eliminate targets that cannot satisfy the workload.
2. **Deterministic scoring** ranks the surviving targets.
3. The result includes a digest, selected target, score components, complete ranking, and per-target rejection reasons.

## Hard constraints

A target is rejected when it violates any material requirement:

- availability
- hourly budget
- compute capacity
- memory capacity
- memory bandwidth
- network capacity
- latency SLO
- power limit
- privacy clearance
- required execution features
- optional grant expiry

There is no fallback `ALLOW` merely because a request is syntactically valid.

## Ranking model

Feasible targets are scored across:

- latency margin
- power margin
- memory-locality / bandwidth headroom
- network headroom
- cost headroom
- architecture preference

Weights are configurable and normalized before use. Ties are broken by `target_id`, so identical inputs produce deterministic placement.

## Install

```bash
python -m pip install -e .
```

This exposes:

```bash
hetero-place
```

## Run

Create a request:

```json
{
  "subject_id": "inference-job-17",
  "budget": 2.0,
  "workload": {
    "compute_tflops": 20,
    "memory_gb": 24,
    "memory_bandwidth_gbps": 500,
    "network_gbps": 50,
    "latency_slo_ms": 20,
    "power_limit_w": 400,
    "privacy": "CONFIDENTIAL",
    "required_features": ["fp16"],
    "preferred_architectures": ["gpu", "apu"]
  },
  "targets": [
    {
      "target_id": "gpu-a",
      "architecture": "gpu",
      "compute_tflops": 40,
      "memory_gb": 48,
      "memory_bandwidth_gbps": 1000,
      "network_gbps": 100,
      "estimated_latency_ms": 5,
      "estimated_power_w": 220,
      "cost_per_hour": 1.2,
      "privacy": "CONFIDENTIAL",
      "features": ["fp16", "bf16"]
    },
    {
      "target_id": "cpu-b",
      "architecture": "cpu",
      "compute_tflops": 12,
      "memory_gb": 128,
      "memory_bandwidth_gbps": 300,
      "network_gbps": 100,
      "estimated_latency_ms": 28,
      "estimated_power_w": 180,
      "cost_per_hour": 0.7,
      "privacy": "RESTRICTED",
      "features": ["fp16"]
    }
  ]
}
```

Execute it:

```bash
hetero-place --input request.json --pretty
```

Or stream JSON through stdin:

```bash
cat request.json | hetero-place --pretty
```

The output is computed from the request. It contains the placement decision, selected target when one exists, deterministic score and ranking, rejected targets with reasons, score components, and a SHA-256 digest over the canonical decision inputs. No static sample receipt is presented as runtime evidence.

## Python API

```python
from hetero_placement_contract import (
    HeterogeneousPlacementContract,
    HeterogeneousPlacementContractRequest,
    PlacementTarget,
    WorkloadSpec,
)

request = HeterogeneousPlacementContractRequest(
    subject_id="job-1",
    budget=2.0,
    workload=WorkloadSpec(compute_tflops=10, memory_gb=8),
    targets=(
        PlacementTarget(
            target_id="gpu-a",
            architecture="gpu",
            compute_tflops=20,
            memory_gb=16,
            memory_bandwidth_gbps=500,
            network_gbps=25,
            estimated_latency_ms=8,
            estimated_power_w=200,
            cost_per_hour=1.0,
        ),
    ),
)

receipt = HeterogeneousPlacementContract().evaluate(request)
print(receipt.as_dict())
```

## Verification

Behavioral tests cover:

- strongest feasible target selection
- hard capacity rejection
- latency and budget rejection
- privacy and required-feature enforcement
- deterministic tie-breaking
- grant expiry
- CLI execution

The implementation was exercised locally with:

```text
6 passed
```

A direct CLI smoke also produced an `ALLOW` receipt with a selected target and score breakdown.

CI installs the package, runs the behavioral suite, and executes the real `hetero-place` command. It no longer runs generic reflection code as a substitute for product behavior.

## Status

**FUNCTIONAL** for its intended purpose as a deterministic placement engine.

This is a model-driven placement tool, not a claim of live AMD fleet scheduling. A future hardware-backed benchmark may strengthen the evidence, but the repository's actual software purpose no longer depends on a placeholder implementation.
