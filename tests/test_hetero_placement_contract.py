from __future__ import annotations

import json

from hetero_placement_contract import (
    Decision,
    HeterogeneousPlacementContract,
    HeterogeneousPlacementContractRequest,
    PlacementTarget,
    PrivacyLevel,
    WorkloadSpec,
    main,
)


def workload(**overrides):
    data = dict(
        compute_tflops=20,
        memory_gb=24,
        memory_bandwidth_gbps=500,
        network_gbps=50,
        latency_slo_ms=20,
        power_limit_w=400,
        privacy=PrivacyLevel.CONFIDENTIAL,
        required_features=("fp16",),
        preferred_architectures=("gpu", "apu"),
    )
    data.update(overrides)
    return WorkloadSpec(**data)


def target(target_id: str, **overrides):
    data = dict(
        target_id=target_id,
        architecture="gpu",
        compute_tflops=40,
        memory_gb=48,
        memory_bandwidth_gbps=1000,
        network_gbps=100,
        estimated_latency_ms=10,
        estimated_power_w=250,
        cost_per_hour=1.0,
        privacy=PrivacyLevel.CONFIDENTIAL,
        features=("fp16", "bf16"),
        available=True,
    )
    data.update(overrides)
    return PlacementTarget(**data)


def test_selects_strongest_feasible_target() -> None:
    mech = HeterogeneousPlacementContract()
    slower = target("slow", estimated_latency_ms=18, estimated_power_w=330, cost_per_hour=1.5)
    faster = target("fast", estimated_latency_ms=5, estimated_power_w=220, cost_per_hour=1.2)
    receipt = mech.evaluate(
        HeterogeneousPlacementContractRequest(
            subject_id="inference-1",
            workload=workload(),
            targets=(slower, faster),
            budget=2.0,
        )
    )
    assert receipt.decision is Decision.ALLOW
    assert receipt.selected_target_id == "fast"
    assert receipt.metrics["feasible_count"] == 2
    assert receipt.metrics["ranking"][0]["target_id"] == "fast"
    assert len(receipt.digest) == 64


def test_hard_constraints_refuse_infeasible_targets() -> None:
    mech = HeterogeneousPlacementContract()
    receipt = mech.evaluate(
        HeterogeneousPlacementContractRequest(
            subject_id="training-1",
            workload=workload(),
            targets=(
                target("memory-starved", memory_gb=8),
                target("too-slow", estimated_latency_ms=50),
                target("too-expensive", cost_per_hour=9.0),
            ),
            budget=2.0,
        )
    )
    assert receipt.decision is Decision.REFUSE
    assert receipt.reasons == ("no_feasible_target",)
    assert "memory_capacity" in receipt.metrics["rejected"]["memory-starved"]
    assert "latency_slo" in receipt.metrics["rejected"]["too-slow"]
    assert "budget_exceeded" in receipt.metrics["rejected"]["too-expensive"]


def test_privacy_and_required_features_are_hard_constraints() -> None:
    mech = HeterogeneousPlacementContract()
    receipt = mech.evaluate(
        HeterogeneousPlacementContractRequest(
            subject_id="private-agent",
            workload=workload(privacy=PrivacyLevel.RESTRICTED, required_features=("fp16", "sev-snp")),
            targets=(
                target("public-gpu", privacy=PrivacyLevel.PUBLIC),
                target("no-sev", privacy=PrivacyLevel.RESTRICTED, features=("fp16",)),
                target("secure", privacy=PrivacyLevel.RESTRICTED, features=("fp16", "sev-snp")),
            ),
            budget=2.0,
        )
    )
    assert receipt.decision is Decision.ALLOW
    assert receipt.selected_target_id == "secure"
    assert "privacy_clearance" in receipt.metrics["rejected"]["public-gpu"]
    assert "missing_features:sev-snp" in receipt.metrics["rejected"]["no-sev"]


def test_ties_are_deterministic_by_target_id() -> None:
    mech = HeterogeneousPlacementContract()
    a = target("a")
    b = target("b")
    req = HeterogeneousPlacementContractRequest(
        subject_id="tie",
        workload=workload(),
        targets=(b, a),
        budget=2.0,
    )
    assert mech.evaluate(req).selected_target_id == "a"
    assert mech.evaluate(req).digest == mech.evaluate(req).digest


def test_expired_grant_refuses_before_placement() -> None:
    receipt = HeterogeneousPlacementContract().evaluate(
        HeterogeneousPlacementContractRequest(
            subject_id="expired",
            workload=workload(),
            targets=(target("a"),),
            budget=2.0,
            not_after=100.0,
            now=101.0,
        )
    )
    assert receipt.decision is Decision.REFUSE
    assert "grant_expired" in receipt.reasons


def test_cli_executes_json_request(tmp_path, capsys) -> None:
    request = {
        "subject_id": "cli-job",
        "budget": 2.0,
        "workload": {
            "compute_tflops": 10,
            "memory_gb": 8,
            "latency_slo_ms": 30,
            "power_limit_w": 400,
        },
        "targets": [
            {
                "target_id": "node-a",
                "architecture": "gpu",
                "compute_tflops": 20,
                "memory_gb": 16,
                "memory_bandwidth_gbps": 500,
                "network_gbps": 25,
                "estimated_latency_ms": 8,
                "estimated_power_w": 200,
                "cost_per_hour": 1.0,
            }
        ],
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    assert main(["--input", str(path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "ALLOW"
    assert output["selected_target_id"] == "node-a"
