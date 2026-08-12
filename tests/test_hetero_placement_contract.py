from __future__ import annotations

from hetero_placement_contract import (
    Decision,
    HeterogeneousPlacementContract,
    HeterogeneousPlacementContractRequest,
)


def _request(targets, **workload_overrides):
    workload = {
        "compute_tflops": 20,
        "memory_gb": 16,
        "bandwidth_gbps": 25,
        "max_latency_ms": 15,
        "device": "gpu",
        "privacy": "trusted",
        "locality": "rack-a",
    }
    workload.update(workload_overrides)
    return HeterogeneousPlacementContractRequest(
        subject_id="inference-batch-42",
        budget=1.0,
        payload={"workload": workload, "targets": targets},
    )


def _target(target_id: str, **overrides):
    target = {
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
    }
    target.update(overrides)
    return target


def test_selects_best_feasible_target() -> None:
    slow = _target("slow", latency_ms=12, utilization=0.50, locality="rack-b")
    fast = _target("fast", latency_ms=2, utilization=0.10, power_watts=250)
    receipt = HeterogeneousPlacementContract().evaluate(_request([slow, fast]))

    assert receipt.decision is Decision.ALLOW
    assert receipt.reasons == ("placement_selected",)
    assert receipt.placement["target_id"] == "fast"
    assert receipt.ranked_candidates[0]["target_id"] == "fast"
    assert receipt.metrics["feasible_count"] == 2
    assert len(receipt.digest) == 64


def test_refuses_when_no_target_is_feasible() -> None:
    tiny = _target("tiny", compute_tflops=10, memory_gb=8, available_memory_gb=8)
    receipt = HeterogeneousPlacementContract().evaluate(_request([tiny]))

    assert receipt.decision is Decision.REFUSE
    assert "no_feasible_target" in receipt.reasons
    assert "compute_insufficient" in receipt.rejected_targets["tiny"]
    assert "memory_insufficient" in receipt.rejected_targets["tiny"]


def test_privacy_is_hard_constraint() -> None:
    public = _target("public-node", privacy="public")
    trusted = _target("trusted-node", privacy="trusted")
    receipt = HeterogeneousPlacementContract().evaluate(
        _request([public, trusted], privacy="trusted")
    )

    assert receipt.decision is Decision.ALLOW
    assert receipt.placement["target_id"] == "trusted-node"
    assert receipt.rejected_targets["public-node"] == ("privacy_insufficient",)


def test_power_cap_is_hard_constraint() -> None:
    hot = _target("hot", power_watts=400)
    cool = _target("cool", power_watts=220)
    receipt = HeterogeneousPlacementContract().evaluate(
        _request([hot, cool], max_power_watts=300)
    )

    assert receipt.decision is Decision.ALLOW
    assert receipt.placement["target_id"] == "cool"
    assert "power_cap_exceeded" in receipt.rejected_targets["hot"]


def test_target_order_does_not_change_result() -> None:
    a = _target("a", latency_ms=5)
    b = _target("b", latency_ms=3)
    mech = HeterogeneousPlacementContract()
    first = mech.evaluate(_request([a, b]))
    second = mech.evaluate(_request([b, a]))

    assert first.placement == second.placement
    assert first.digest == second.digest


def test_rejects_invalid_input_envelope() -> None:
    receipt = HeterogeneousPlacementContract().evaluate(
        HeterogeneousPlacementContractRequest(subject_id=" ", payload={}, budget=0.0)
    )

    assert receipt.decision is Decision.REFUSE
    assert "subject_id_missing" in receipt.reasons
    assert "budget_non_positive" in receipt.reasons
    assert "workload_missing" in receipt.reasons
    assert "targets_missing" in receipt.reasons
