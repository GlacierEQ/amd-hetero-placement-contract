"""Deterministic heterogeneous workload placement engine.

This module is vendor-neutral. It chooses the strongest feasible execution target
for a workload using hard capacity/privacy constraints followed by a deterministic
multi-objective score over latency, power, memory locality, network headroom,
cost, and architecture preference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Mapping, Sequence


def _digest(obj: object) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Decision(str, Enum):
    ALLOW = "ALLOW"
    REFUSE = "REFUSE"


class PrivacyLevel(IntEnum):
    PUBLIC = 0
    CONFIDENTIAL = 1
    RESTRICTED = 2

    @classmethod
    def parse(cls, value: str | int | "PrivacyLevel") -> "PrivacyLevel":
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls(value)
        return cls[str(value).strip().upper()]


@dataclass(frozen=True)
class WorkloadSpec:
    compute_tflops: float
    memory_gb: float
    memory_bandwidth_gbps: float = 0.0
    network_gbps: float = 0.0
    latency_slo_ms: float = 0.0
    power_limit_w: float = 0.0
    privacy: PrivacyLevel = PrivacyLevel.PUBLIC
    required_features: tuple[str, ...] = ()
    preferred_architectures: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WorkloadSpec":
        return cls(
            compute_tflops=float(value.get("compute_tflops", 0.0)),
            memory_gb=float(value.get("memory_gb", 0.0)),
            memory_bandwidth_gbps=float(value.get("memory_bandwidth_gbps", 0.0)),
            network_gbps=float(value.get("network_gbps", 0.0)),
            latency_slo_ms=float(value.get("latency_slo_ms", 0.0)),
            power_limit_w=float(value.get("power_limit_w", 0.0)),
            privacy=PrivacyLevel.parse(value.get("privacy", "PUBLIC")),
            required_features=tuple(sorted({str(x) for x in value.get("required_features", [])})),
            preferred_architectures=tuple(
                str(x).strip().lower() for x in value.get("preferred_architectures", [])
            ),
        )


@dataclass(frozen=True)
class PlacementTarget:
    target_id: str
    architecture: str
    compute_tflops: float
    memory_gb: float
    memory_bandwidth_gbps: float
    network_gbps: float
    estimated_latency_ms: float
    estimated_power_w: float
    cost_per_hour: float
    privacy: PrivacyLevel = PrivacyLevel.PUBLIC
    features: tuple[str, ...] = ()
    available: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PlacementTarget":
        return cls(
            target_id=str(value.get("target_id", "")).strip(),
            architecture=str(value.get("architecture", "unknown")).strip().lower(),
            compute_tflops=float(value.get("compute_tflops", 0.0)),
            memory_gb=float(value.get("memory_gb", 0.0)),
            memory_bandwidth_gbps=float(value.get("memory_bandwidth_gbps", 0.0)),
            network_gbps=float(value.get("network_gbps", 0.0)),
            estimated_latency_ms=float(value.get("estimated_latency_ms", 0.0)),
            estimated_power_w=float(value.get("estimated_power_w", 0.0)),
            cost_per_hour=float(value.get("cost_per_hour", 0.0)),
            privacy=PrivacyLevel.parse(value.get("privacy", "PUBLIC")),
            features=tuple(sorted({str(x) for x in value.get("features", [])})),
            available=bool(value.get("available", True)),
        )


@dataclass(frozen=True)
class PlacementWeights:
    latency: float = 0.25
    power: float = 0.20
    memory_locality: float = 0.20
    network: float = 0.10
    cost: float = 0.15
    architecture_preference: float = 0.10

    def normalized(self) -> "PlacementWeights":
        values = [
            self.latency,
            self.power,
            self.memory_locality,
            self.network,
            self.cost,
            self.architecture_preference,
        ]
        if any(value < 0 for value in values):
            raise ValueError("placement weights must be non-negative")
        total = sum(values)
        if total <= 0:
            raise ValueError("at least one placement weight must be positive")
        return PlacementWeights(*(value / total for value in values))


@dataclass(frozen=True)
class HeterogeneousPlacementContractRequest:
    subject_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    budget: float = 1.0
    grant_id: str | None = None
    not_after: float | None = None
    workload: WorkloadSpec | None = None
    targets: tuple[PlacementTarget, ...] = ()
    weights: PlacementWeights = field(default_factory=PlacementWeights)
    now: float | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "HeterogeneousPlacementContractRequest":
        workload_raw = value.get("workload")
        targets_raw = value.get("targets", [])
        weights_raw = value.get("weights")
        workload = WorkloadSpec.from_mapping(workload_raw) if isinstance(workload_raw, Mapping) else None
        targets = tuple(
            PlacementTarget.from_mapping(item)
            for item in targets_raw
            if isinstance(item, Mapping)
        )
        weights = PlacementWeights(**dict(weights_raw)) if isinstance(weights_raw, Mapping) else PlacementWeights()
        return cls(
            subject_id=str(value.get("subject_id", "")),
            payload=dict(value.get("payload", {})) if isinstance(value.get("payload", {}), Mapping) else {},
            budget=float(value.get("budget", 1.0)),
            grant_id=str(value["grant_id"]) if value.get("grant_id") is not None else None,
            not_after=float(value["not_after"]) if value.get("not_after") is not None else None,
            workload=workload,
            targets=targets,
            weights=weights,
            now=float(value["now"]) if value.get("now") is not None else None,
        )


@dataclass(frozen=True)
class HeterogeneousPlacementContractReceipt:
    decision: Decision
    reasons: tuple[str, ...]
    digest: str
    selected_target_id: str | None = None
    score: float | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "digest": self.digest,
            "selected_target_id": self.selected_target_id,
            "score": self.score,
            "metrics": self.metrics,
        }


class HeterogeneousPlacementContract:
    """Choose a feasible heterogeneous execution target deterministically."""

    def _resolve_workload(self, req: HeterogeneousPlacementContractRequest) -> WorkloadSpec | None:
        if req.workload is not None:
            return req.workload
        raw = req.payload.get("workload")
        return WorkloadSpec.from_mapping(raw) if isinstance(raw, Mapping) else None

    def _resolve_targets(self, req: HeterogeneousPlacementContractRequest) -> tuple[PlacementTarget, ...]:
        if req.targets:
            return req.targets
        raw = req.payload.get("targets", [])
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            return ()
        return tuple(PlacementTarget.from_mapping(item) for item in raw if isinstance(item, Mapping))

    @staticmethod
    def _validation_errors(workload: WorkloadSpec) -> list[str]:
        errors: list[str] = []
        if workload.compute_tflops <= 0:
            errors.append("workload_compute_non_positive")
        if workload.memory_gb <= 0:
            errors.append("workload_memory_non_positive")
        for name in (
            "memory_bandwidth_gbps",
            "network_gbps",
            "latency_slo_ms",
            "power_limit_w",
        ):
            if getattr(workload, name) < 0:
                errors.append(f"workload_{name}_negative")
        return errors

    @staticmethod
    def _rejection_reasons(
        target: PlacementTarget,
        workload: WorkloadSpec,
        budget: float,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if not target.target_id:
            reasons.append("target_id_missing")
        if not target.available:
            reasons.append("unavailable")
        if target.cost_per_hour > budget:
            reasons.append("budget_exceeded")
        if target.compute_tflops < workload.compute_tflops:
            reasons.append("compute_capacity")
        if target.memory_gb < workload.memory_gb:
            reasons.append("memory_capacity")
        if target.memory_bandwidth_gbps < workload.memory_bandwidth_gbps:
            reasons.append("memory_bandwidth")
        if target.network_gbps < workload.network_gbps:
            reasons.append("network_capacity")
        if workload.latency_slo_ms > 0 and target.estimated_latency_ms > workload.latency_slo_ms:
            reasons.append("latency_slo")
        if workload.power_limit_w > 0 and target.estimated_power_w > workload.power_limit_w:
            reasons.append("power_limit")
        if target.privacy < workload.privacy:
            reasons.append("privacy_clearance")
        missing = sorted(set(workload.required_features) - set(target.features))
        if missing:
            reasons.append("missing_features:" + ",".join(missing))
        return tuple(reasons)

    @staticmethod
    def _ratio_score(capacity: float, requirement: float) -> float:
        if requirement <= 0:
            return 1.0
        return max(0.0, min(1.0, capacity / (2.0 * requirement)))

    @classmethod
    def _score(
        cls,
        target: PlacementTarget,
        workload: WorkloadSpec,
        budget: float,
        weights: PlacementWeights,
    ) -> tuple[float, dict[str, float]]:
        latency = (
            1.0
            if workload.latency_slo_ms <= 0
            else max(0.0, 1.0 - target.estimated_latency_ms / workload.latency_slo_ms)
        )
        power = (
            1.0
            if workload.power_limit_w <= 0
            else max(0.0, 1.0 - target.estimated_power_w / workload.power_limit_w)
        )
        memory_locality = cls._ratio_score(
            target.memory_bandwidth_gbps,
            workload.memory_bandwidth_gbps,
        )
        network = cls._ratio_score(target.network_gbps, workload.network_gbps)
        cost = max(0.0, 1.0 - target.cost_per_hour / budget) if budget > 0 else 0.0
        preferred = tuple(x.lower() for x in workload.preferred_architectures)
        architecture_preference = 1.0 if not preferred or target.architecture in preferred else 0.0
        components = {
            "latency": latency,
            "power": power,
            "memory_locality": memory_locality,
            "network": network,
            "cost": cost,
            "architecture_preference": architecture_preference,
        }
        score = (
            weights.latency * latency
            + weights.power * power
            + weights.memory_locality * memory_locality
            + weights.network * network
            + weights.cost * cost
            + weights.architecture_preference * architecture_preference
        )
        return score, components

    def evaluate(self, req: HeterogeneousPlacementContractRequest) -> HeterogeneousPlacementContractReceipt:
        errors: list[str] = []
        subject_id = str(req.subject_id).strip()
        if not subject_id:
            errors.append("subject_id_missing")
        if req.budget <= 0:
            errors.append("budget_non_positive")
        now = req.now if req.now is not None else time.time()
        if req.not_after is not None and now > req.not_after:
            errors.append("grant_expired")

        workload = self._resolve_workload(req)
        targets = self._resolve_targets(req)
        if workload is None:
            errors.append("workload_missing")
        else:
            errors.extend(self._validation_errors(workload))
        if not targets:
            errors.append("targets_missing")

        canonical_request = {
            "subject_id": subject_id,
            "budget": req.budget,
            "grant_id": req.grant_id,
            "not_after": req.not_after,
            "workload": asdict(workload) if workload else None,
            "targets": [asdict(target) for target in targets],
            "weights": asdict(req.weights),
        }
        if errors:
            body = {**canonical_request, "decision": Decision.REFUSE.value, "reasons": sorted(set(errors))}
            return HeterogeneousPlacementContractReceipt(
                decision=Decision.REFUSE,
                reasons=tuple(sorted(set(errors))),
                digest=_digest(body),
                metrics={"candidate_count": len(targets), "feasible_count": 0},
            )

        assert workload is not None
        try:
            weights = req.weights.normalized()
        except ValueError as exc:
            reasons = (f"invalid_weights:{exc}",)
            return HeterogeneousPlacementContractReceipt(
                decision=Decision.REFUSE,
                reasons=reasons,
                digest=_digest({**canonical_request, "decision": "REFUSE", "reasons": reasons}),
                metrics={"candidate_count": len(targets), "feasible_count": 0},
            )

        rejected: dict[str, list[str]] = {}
        ranked: list[tuple[float, str, PlacementTarget, dict[str, float]]] = []
        for target in targets:
            reasons = self._rejection_reasons(target, workload, req.budget)
            if reasons:
                rejected[target.target_id or "<missing>"] = list(reasons)
                continue
            score, components = self._score(target, workload, req.budget, weights)
            ranked.append((score, target.target_id, target, components))

        if not ranked:
            reasons = ("no_feasible_target",)
            body = {**canonical_request, "decision": Decision.REFUSE.value, "rejected": rejected}
            return HeterogeneousPlacementContractReceipt(
                decision=Decision.REFUSE,
                reasons=reasons,
                digest=_digest(body),
                metrics={
                    "candidate_count": len(targets),
                    "feasible_count": 0,
                    "rejected": rejected,
                },
            )

        ranked.sort(key=lambda item: (-item[0], item[1]))
        best_score, _, best_target, components = ranked[0]
        ranking = [
            {"target_id": target.target_id, "score": round(score, 8)}
            for score, _, target, _ in ranked
        ]
        body = {
            **canonical_request,
            "decision": Decision.ALLOW.value,
            "selected_target_id": best_target.target_id,
            "score": round(best_score, 12),
            "ranking": ranking,
        }
        return HeterogeneousPlacementContractReceipt(
            decision=Decision.ALLOW,
            reasons=("feasible_target_selected",),
            digest=_digest(body),
            selected_target_id=best_target.target_id,
            score=best_score,
            metrics={
                "candidate_count": len(targets),
                "feasible_count": len(ranked),
                "selected_architecture": best_target.architecture,
                "score_components": {k: round(v, 8) for k, v in components.items()},
                "ranking": ranking,
                "rejected": rejected,
            },
        )


Mechanism = HeterogeneousPlacementContract


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic heterogeneous workload placer")
    parser.add_argument("--input", type=Path, help="JSON request file; stdin when omitted")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
    try:
        value = json.loads(raw)
        if not isinstance(value, Mapping):
            raise ValueError("request must be a JSON object")
        request = HeterogeneousPlacementContractRequest.from_mapping(value)
        receipt = HeterogeneousPlacementContract().evaluate(request)
    except (ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"decision": "REFUSE", "reasons": [f"invalid_request:{exc}"]}))
        return 2
    print(json.dumps(receipt.as_dict(), indent=2 if args.pretty else None, sort_keys=True))
    return 0 if receipt.decision is Decision.ALLOW else 2


if __name__ == "__main__":
    raise SystemExit(main())
