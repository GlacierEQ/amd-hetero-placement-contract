"""Deterministic heterogeneous workload placement engine.

Consumes a workload descriptor and caller-supplied topology, rejects infeasible
targets, and deterministically ranks feasible targets using transparent
latency, headroom, energy-efficiency, privacy, and locality factors.

This is vendor-neutral. All measurements are supplied by the caller; the
engine makes no claims about real AMD hardware or proprietary systems.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _digest(obj: object) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Decision(str, Enum):
    ALLOW = "ALLOW"
    REFUSE = "REFUSE"


@dataclass(frozen=True)
class HeterogeneousPlacementContractRequest:
    subject_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    budget: float = 1.0
    grant_id: str | None = None
    not_after: float | None = None


@dataclass(frozen=True)
class HeterogeneousPlacementContractReceipt:
    decision: Decision
    reasons: tuple[str, ...]
    digest: str
    metrics: dict[str, Any] = field(default_factory=dict)
    placement: dict[str, Any] = field(default_factory=dict)
    ranked_candidates: tuple[dict[str, Any], ...] = ()
    rejected_targets: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "digest": self.digest,
            "metrics": self.metrics,
            "placement": self.placement,
            "ranked_candidates": list(self.ranked_candidates),
            "rejected_targets": {k: list(v) for k, v in self.rejected_targets.items()},
        }


class HeterogeneousPlacementContract:
    """Filter infeasible targets and rank feasible ones deterministically."""

    MIN_BUDGET = 0.0
    PRIVACY_LEVEL = {"public": 0, "trusted": 1, "local": 2, "restricted": 3}
    WEIGHTS = {
        "latency": 0.30,
        "compute_headroom": 0.20,
        "memory_headroom": 0.15,
        "bandwidth_headroom": 0.15,
        "energy_efficiency": 0.10,
        "locality": 0.10,
    }
    REFERENCE_TFLOPS_PER_WATT = 0.50

    @staticmethod
    def _number(obj: dict[str, Any], key: str, *, minimum: float = 0.0) -> tuple[float | None, str | None]:
        try:
            value = float(obj[key])
        except (KeyError, TypeError, ValueError):
            return None, f"{key}_invalid"
        if value < minimum:
            return None, f"{key}_below_minimum"
        return value, None

    def _normalize_workload(self, raw: Any) -> tuple[dict[str, Any] | None, list[str]]:
        if not isinstance(raw, dict):
            return None, ["workload_missing"]

        errors: list[str] = []
        values: dict[str, float] = {}
        for key, minimum in (
            ("compute_tflops", 0.000001),
            ("memory_gb", 0.000001),
            ("bandwidth_gbps", 0.0),
            ("max_latency_ms", 0.000001),
        ):
            value, error = self._number(raw, key, minimum=minimum)
            if error:
                errors.append(f"workload_{error}")
            else:
                values[key] = float(value)

        privacy = str(raw.get("privacy", "public")).lower()
        if privacy not in self.PRIVACY_LEVEL:
            errors.append("workload_privacy_invalid")

        device = str(raw.get("device", "any")).lower().strip()
        if not device:
            errors.append("workload_device_invalid")

        max_power = raw.get("max_power_watts")
        if max_power is not None:
            try:
                max_power = float(max_power)
                if max_power <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append("workload_max_power_watts_invalid")

        if errors:
            return None, errors

        result: dict[str, Any] = {
            **values,
            "privacy": privacy,
            "device": device,
            "locality": str(raw.get("locality", "")).strip() or None,
        }
        if max_power is not None:
            result["max_power_watts"] = max_power
        return result, []

    def _normalize_target(self, raw: Any, index: int) -> tuple[dict[str, Any] | None, list[str]]:
        if not isinstance(raw, dict):
            return None, [f"target_{index}_not_object"]

        target_id = str(raw.get("id", "")).strip()
        if not target_id:
            return None, [f"target_{index}_id_missing"]

        errors: list[str] = []
        values: dict[str, float] = {}
        for key, minimum in (
            ("compute_tflops", 0.000001),
            ("memory_gb", 0.000001),
            ("bandwidth_gbps", 0.0),
            ("latency_ms", 0.0),
            ("power_watts", 0.000001),
        ):
            value, error = self._number(raw, key, minimum=minimum)
            if error:
                errors.append(f"target_{target_id}_{error}")
            else:
                values[key] = float(value)

        try:
            utilization = float(raw.get("utilization", 0.0))
            if not 0.0 <= utilization < 1.0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"target_{target_id}_utilization_invalid")
            utilization = 1.0

        privacy = str(raw.get("privacy", "public")).lower()
        if privacy not in self.PRIVACY_LEVEL:
            errors.append(f"target_{target_id}_privacy_invalid")

        device = str(raw.get("device", "")).lower().strip()
        if not device:
            errors.append(f"target_{target_id}_device_missing")

        if errors:
            return None, errors

        try:
            available_memory = float(raw.get("available_memory_gb", values["memory_gb"]))
            if available_memory < 0 or available_memory > values["memory_gb"]:
                raise ValueError
        except (TypeError, ValueError):
            return None, [f"target_{target_id}_available_memory_gb_invalid"]

        return {
            "id": target_id,
            "device": device,
            **values,
            "available_memory_gb": available_memory,
            "utilization": utilization,
            "privacy": privacy,
            "locality": str(raw.get("locality", "")).strip() or None,
        }, []

    def _feasibility(self, workload: dict[str, Any], target: dict[str, Any]) -> list[str]:
        failures: list[str] = []
        available_compute = target["compute_tflops"] * (1.0 - target["utilization"])
        if workload["device"] != "any" and target["device"] != workload["device"]:
            failures.append("device_mismatch")
        if available_compute < workload["compute_tflops"]:
            failures.append("compute_insufficient")
        if target["available_memory_gb"] < workload["memory_gb"]:
            failures.append("memory_insufficient")
        if target["bandwidth_gbps"] < workload["bandwidth_gbps"]:
            failures.append("bandwidth_insufficient")
        if target["latency_ms"] > workload["max_latency_ms"]:
            failures.append("latency_exceeded")
        if self.PRIVACY_LEVEL[target["privacy"]] < self.PRIVACY_LEVEL[workload["privacy"]]:
            failures.append("privacy_insufficient")
        if workload.get("max_power_watts") is not None and target["power_watts"] > workload["max_power_watts"]:
            failures.append("power_cap_exceeded")
        return failures

    @staticmethod
    def _headroom(capacity: float, required: float) -> float:
        if required <= 0:
            return 1.0
        return max(0.0, min(1.0, (capacity - required) / required))

    def _score(self, workload: dict[str, Any], target: dict[str, Any]) -> tuple[float, dict[str, float]]:
        available_compute = target["compute_tflops"] * (1.0 - target["utilization"])
        components = {
            "latency": max(0.0, min(1.0, 1.0 - target["latency_ms"] / workload["max_latency_ms"])),
            "compute_headroom": self._headroom(available_compute, workload["compute_tflops"]),
            "memory_headroom": self._headroom(target["available_memory_gb"], workload["memory_gb"]),
            "bandwidth_headroom": self._headroom(target["bandwidth_gbps"], max(workload["bandwidth_gbps"], 0.000001)),
            "energy_efficiency": max(
                0.0,
                min(1.0, (available_compute / target["power_watts"]) / self.REFERENCE_TFLOPS_PER_WATT),
            ),
            "locality": 1.0 if workload.get("locality") and target.get("locality") == workload.get("locality") else 0.0,
        }
        score = sum(self.WEIGHTS[name] * value for name, value in components.items())
        return round(score, 6), {name: round(value, 6) for name, value in components.items()}

    def evaluate(self, req: HeterogeneousPlacementContractRequest) -> HeterogeneousPlacementContractReceipt:
        reasons: list[str] = []
        if not str(req.subject_id or "").strip():
            reasons.append("subject_id_missing")
        if req.budget <= self.MIN_BUDGET:
            reasons.append("budget_non_positive")

        if not isinstance(req.payload, dict):
            reasons.append("payload_not_object")
            payload: dict[str, Any] = {}
        else:
            payload = req.payload

        workload, workload_errors = self._normalize_workload(payload.get("workload"))
        reasons.extend(workload_errors)

        raw_targets = payload.get("targets", [])
        if not isinstance(raw_targets, list) or not raw_targets:
            reasons.append("targets_missing")
            raw_targets = []

        targets: list[dict[str, Any]] = []
        seen: set[str] = set()
        for i, raw in enumerate(raw_targets):
            target, errors = self._normalize_target(raw, i)
            reasons.extend(errors)
            if target is None:
                continue
            if target["id"] in seen:
                reasons.append(f"target_{target['id']}_duplicate")
                continue
            seen.add(target["id"])
            targets.append(target)

        ranked: list[dict[str, Any]] = []
        rejected: dict[str, tuple[str, ...]] = {}
        if workload is not None:
            for target in targets:
                failures = self._feasibility(workload, target)
                if failures:
                    rejected[target["id"]] = tuple(failures)
                    continue
                score, components = self._score(workload, target)
                ranked.append({
                    "target_id": target["id"],
                    "score": score,
                    "components": components,
                    "available_compute_tflops": round(target["compute_tflops"] * (1.0 - target["utilization"]), 6),
                    "available_memory_gb": target["available_memory_gb"],
                    "latency_ms": target["latency_ms"],
                    "power_watts": target["power_watts"],
                })

        ranked.sort(key=lambda item: (-item["score"], item["target_id"]))

        if workload is not None and targets and not ranked and not reasons:
            reasons.append("no_feasible_target")

        placement: dict[str, Any] = {}
        decision = Decision.REFUSE
        if not reasons and ranked:
            decision = Decision.ALLOW
            winner = ranked[0]
            placement = {
                "target_id": winner["target_id"],
                "score": winner["score"],
                "workload": workload,
            }
            reasons = ["placement_selected"]

        digest_body = {
            "schema": "glaciereq.heterogeneous-placement.v1",
            "subject_id": req.subject_id,
            "workload": workload,
            "targets": sorted(targets, key=lambda t: t["id"]),
            "placement": placement,
            "ranked_candidates": ranked,
            "rejected_targets": rejected,
            "decision": decision.value,
            "reasons": reasons,
        }
        metrics = {
            "candidate_count": len(targets),
            "feasible_count": len(ranked),
            "rejected_count": len(rejected),
            "selected_score": ranked[0]["score"] if ranked else None,
            "budget": req.budget,
        }
        return HeterogeneousPlacementContractReceipt(
            decision=decision,
            reasons=tuple(reasons),
            digest=_digest(digest_body),
            metrics=metrics,
            placement=placement,
            ranked_candidates=tuple(ranked),
            rejected_targets=rejected,
        )

    def compare(self, req: HeterogeneousPlacementContractRequest) -> list[dict[str, Any]]:
        """Return ranked feasible candidates for inspection."""
        return list(self.evaluate(req).ranked_candidates)


Mechanism = HeterogeneousPlacementContract
