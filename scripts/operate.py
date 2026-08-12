#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hetero_placement_contract import Decision, HeterogeneousPlacementContract, HeterogeneousPlacementContractRequest

DEMO = {
    "subject_id": "demo-job",
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
            },
            {
                "id": "node-b",
                "device": "gpu",
                "compute_tflops": 96,
                "memory_gb": 64,
                "available_memory_gb": 40,
                "bandwidth_gbps": 100,
                "latency_ms": 11,
                "power_watts": 320,
                "utilization": 0.45,
                "privacy": "trusted",
                "locality": "rack-b"
            }
        ]
    }
}


def load_request(path: str | None) -> dict:
    if path is None:
        return DEMO
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("input JSON must be an object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Run heterogeneous workload placement")
    parser.add_argument("--input")
    parser.add_argument("--output")
    args = parser.parse_args()

    data = load_request(args.input)
    request = HeterogeneousPlacementContractRequest(
        subject_id=str(data.get("subject_id", "")),
        payload=data.get("payload", {}),
        budget=float(data.get("budget", 1.0)),
        grant_id=data.get("grant_id"),
        not_after=data.get("not_after"),
    )
    receipt = HeterogeneousPlacementContract().evaluate(request)
    text = json.dumps(receipt.as_dict(), indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if receipt.decision is Decision.ALLOW else 2


if __name__ == "__main__":
    raise SystemExit(main())
