from __future__ import annotations

import json

from hetero_placement_contract import (
    Decision,
    HeterogeneousPlacementContract,
    HeterogeneousPlacementContractRequest,
    main,
)


def workload(**overrides):
    value = {
        "compute_tflops": 20,
        "memory_gb": 16,
        "bandwidth_gbps": 25,
        "max_latency_ms": 15,
        "device": "gpu",
        "privacy": "trusted",
        "locality": "rack-a",
        "required_features": ["fp16"],
    }
    value.update(overrides)
    return value


def target(target_id: str, **overrides):
    value = {
        "id": target_id,
        "device": "gpu",
        "compute_tflops": 80,
        "memory_gb": 64,
        "available_memory_gb": 48,
        "bandwidth_gbps": 100,
        "latency_ms": 5,
        "power_watts": 300,
        "utilization": 0.25,
        "privacy": "trusted",
        "locality": "rack-a",
        "cost_per_hour": 0.5,
        "available": True,
        "features": ["fp16", "bf16"],
    }
    value.update(overrides)
    return value


def request(targets, *, budget=1.0, **kwargs):
    return HeterogeneousPlacementContractRequest(
        subject_id="completion-test",
        budget=budget,
        payload={"workload": workload(), "targets": targets},
        **kwargs,
    )


def test_budget_is_real_target_constraint() -> None:
    receipt = HeterogeneousPlacementContract().evaluate(
        request([target("expensive", cost_per_hour=2.0)], budget=1.0)
    )
    assert receipt.decision is Decision.REFUSE
    assert "budget_exceeded" in receipt.rejected_targets["expensive"]


def test_cost_participates_in_ranking() -> None:
    expensive = target("expensive", cost_per_hour=0.9)
    cheap = target("cheap", cost_per_hour=0.1)
    receipt = HeterogeneousPlacementContract().evaluate(
        request([expensive, cheap], budget=1.0)
    )
    assert receipt.decision is Decision.ALLOW
    assert receipt.placement["target_id"] == "cheap"
    assert receipt.ranked_candidates[0]["components"]["cost_headroom"] > (
        receipt.ranked_candidates[1]["components"]["cost_headroom"]
    )


def test_unavailable_and_missing_feature_targets_refuse() -> None:
    unavailable = target("offline", available=False)
    missing = target("missing", features=["bf16"])
    receipt = HeterogeneousPlacementContract().evaluate(
        request([unavailable, missing])
    )
    assert receipt.decision is Decision.REFUSE
    assert "target_unavailable" in receipt.rejected_targets["offline"]
    assert "missing_features:fp16" in receipt.rejected_targets["missing"]


def test_expired_authority_refuses() -> None:
    receipt = HeterogeneousPlacementContract().evaluate(
        request([target("gpu")], grant_id="grant-1", not_after=100.0, now=101.0)
    )
    assert receipt.decision is Decision.REFUSE
    assert "grant_expired" in receipt.reasons


def test_cli_executes_top_level_workload_request(tmp_path, capsys) -> None:
    payload = {
        "subject_id": "cli-placement",
        "budget": 1.0,
        "workload": workload(),
        "targets": [target("gpu")],
    }
    request_path = tmp_path / "request.json"
    receipt_path = tmp_path / "receipt.json"
    request_path.write_text(json.dumps(payload), encoding="utf-8")

    assert main([
        "--input",
        str(request_path),
        "--output",
        str(receipt_path),
    ]) == 0
    stdout = json.loads(capsys.readouterr().out)
    persisted = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert stdout == persisted
    assert persisted["decision"] == "ALLOW"
    assert persisted["placement"]["target_id"] == "gpu"
