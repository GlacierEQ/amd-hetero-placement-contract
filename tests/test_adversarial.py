from __future__ import annotations

from hetero_placement_contract import (
    Decision,
    HeterogeneousPlacementContract,
    HeterogeneousPlacementContractRequest,
)


def _evaluate(workload, targets):
    return HeterogeneousPlacementContract().evaluate(
        HeterogeneousPlacementContractRequest(
            subject_id="job",
            payload={"workload": workload, "targets": targets},
            budget=1.0,
        )
    )


def _workload(**overrides):
    value = {
        "compute_tflops": 10,
        "memory_gb": 8,
        "bandwidth_gbps": 10,
        "max_latency_ms": 20,
        "device": "gpu",
        "privacy": "public",
    }
    value.update(overrides)
    return value


def _target(target_id="gpu-0", **overrides):
    value = {
        "id": target_id,
        "device": "gpu",
        "compute_tflops": 40,
        "memory_gb": 32,
        "available_memory_gb": 24,
        "bandwidth_gbps": 50,
        "latency_ms": 4,
        "power_watts": 200,
        "utilization": 0.25,
        "privacy": "trusted",
    }
    value.update(overrides)
    return value


def test_high_utilization_reduces_available_compute() -> None:
    overloaded = _target(utilization=0.90)
    receipt = _evaluate(_workload(compute_tflops=8), [overloaded])
    assert receipt.decision is Decision.REFUSE
    assert "compute_insufficient" in receipt.rejected_targets["gpu-0"]


def test_memory_availability_not_total_capacity_controls_feasibility() -> None:
    pressured = _target(memory_gb=64, available_memory_gb=4)
    receipt = _evaluate(_workload(memory_gb=8), [pressured])
    assert receipt.decision is Decision.REFUSE
    assert "memory_insufficient" in receipt.rejected_targets["gpu-0"]


def test_latency_boundary_is_inclusive() -> None:
    exact = _target(latency_ms=20)
    receipt = _evaluate(_workload(max_latency_ms=20), [exact])
    assert receipt.decision is Decision.ALLOW


def test_device_mismatch_is_rejected() -> None:
    cpu = _target(device="cpu")
    receipt = _evaluate(_workload(device="gpu"), [cpu])
    assert receipt.decision is Decision.REFUSE
    assert "device_mismatch" in receipt.rejected_targets["gpu-0"]


def test_duplicate_target_identity_is_input_error() -> None:
    receipt = _evaluate(_workload(), [_target("dup"), _target("dup")])
    assert receipt.decision is Decision.REFUSE
    assert "target_dup_duplicate" in receipt.reasons


def test_tie_break_is_deterministic_by_target_id() -> None:
    b = _target("b")
    a = _target("a")
    receipt = _evaluate(_workload(), [b, a])
    assert receipt.decision is Decision.ALLOW
    assert receipt.placement["target_id"] == "a"


def test_invalid_utilization_is_rejected() -> None:
    invalid = _target(utilization=1.0)
    receipt = _evaluate(_workload(), [invalid])
    assert receipt.decision is Decision.REFUSE
    assert "target_gpu-0_utilization_invalid" in receipt.reasons
