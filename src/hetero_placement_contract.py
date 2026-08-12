"""Deterministic heterogeneous workload placement engine.

Consumes a workload descriptor and caller-supplied topology, rejects infeasible
targets, and deterministically ranks feasible targets using transparent
latency, headroom, energy-efficiency, locality, and cost factors.

This is vendor-neutral. All measurements are supplied by the caller; the
engine makes no claims about real AMD hardware or proprietary systems.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


def _digest(obj: object) -> str:
    payload = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Decision(str, Enum):
    ALLOW = "ALLOW"
    REFUSE = "REFUSE"


@dataclass(frozen=True)
class HeterogeneousPlacementContractRequest:
    subject_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    budget: float = 1.0
    grant_id: Optional[str] = None
    not_after: Optional[float] = None
    now: Optional[float] = None


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
        "latency": 0.25,
        "compute_headroom": 0.20,
        "memory_headroom": 0.15,
        "bandwidth_headroom": 0.15,
        "energy_efficiency": 0.10,
        "locality": 0.05,
        "cost_headroom": 0.10,
    }
    REFERENCE_TFLOPS_PER_WATT = 0.50

    @staticmethod
    def _number(
        obj: Mapping[str, Any],
        key: str,
        *,
        minimum: float = 0.0,
    ) -> tuple[Optional[float], Optional[str]]:
        try:
            value = float(obj[key])
        except (KeyError, TypeError, ValueError):
            return None, f"{key}_invalid"
        if value < minimum:
            return None, f"{key}_below_minimum"
        return value, None

    @staticmethod
    def _string_set(value: Any, label: str) -> tuple[tuple[str, ...], list[str]]:
        if value is None:
            return (), []
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            return (), [f"{label}_invalid"]
        normalized = tuple(sorted({str(item).strip().lower() for item in value if str(item).strip()}))
        return normalized, []

    def _normalize_workload(self, raw: Any) -> tuple[Optional[dict[str, Any]], list[str]]:
        if not isinstance(raw, Mapping):
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

        required_features, feature_errors = self._string_set(
            raw.get("required_features", []),
            "workload_required_features",
        )
        errors.extend(feature_errors)

        if errors:
            return None, errors

        result: dict[str, Any] = {
            **values,
            "privacy": privacy,
            "device": device,
            "locality": str(raw.get("locality", "")).strip() or None,
            "required_features": required_features,
        }
        if max_power is not None:
            result["max_power_watts"] = max_power
        return result, []

    def _normalize_target(self, raw: Any, index: int) -> tuple[Optional[dict[str, Any]], list[str]]:
        if not isinstance(raw, Mapping):
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

        try:
            cost_per_hour = float(raw.get("cost_per_hour", 0.0))
            if cost_per_hour < 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"target_{target_id}_cost_per_hour_invalid")
            cost_per_hour = 0.0

        available = raw.get("available", True)
        if not isinstance(available, bool):
            errors.append(f"target_{target_id}_available_invalid")
            available = False

        features, feature_errors = self._string_set(
            raw.get("features", []),
            f"target_{target_id}_features",
        )
        errors.extend(feature_errors)

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
            "cost_per_hour": cost_per_hour,
            "available": available,
            "features": features,
        }, []

    def _feasibility(
        self,
        workload: dict[str, Any],
        target: dict[str, Any],
        budget: float,
    ) -> list[str]:
        failures: list[str] = []
        available_compute = target["compute_tflops"] * (1.0 - target["utilization"])
        if not target["available"]:
            failures.append("target_unavailable")
        if target["cost_per_hour"] > budget:
            failures.append("budget_exceeded")
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
        if (
            workload.get("max_power_watts") is not None
            and target["power_watts"] > workload["max_power_watts"]
        ):
            failures.append("power_cap_exceeded")
        missing_features = sorted(set(workload["required_features"]) - set(target["features"]))
        if missing_features:
            failures.append("missing_features:" + ",".join(missing_features))
        return failures

    @staticmethod
    def _headroom(capacity: float, required: float) -> float:
        if required <= 0:
            return 1.0
        return max(0.0, min(1.0, (capacity - required) / required))

    def _score(
        self,
        workload: dict[str, Any],
        target: dict[str, Any],
        budget: float,
    ) -> tuple[float, dict[str, float]]:
        available_compute = target["compute_tflops"] * (1.0 - target["utilization"])
        components = {
            "latency": max(
                0.0,
                min(1.0, 1.0 - target["latency_ms"] / workload["max_latency_ms"]),
            ),
            "compute_headroom": self._headroom(
                available_compute,
                workload["compute_tflops"],
            ),
            "memory_headroom": self._headroom(
                target["available_memory_gb"],
                workload["memory_gb"],
            ),
            "bandwidth_headroom": self._headroom(
                target["bandwidth_gbps"],
                max(workload["bandwidth_gbps"], 0.000001),
            ),
            "energy_efficiency": max(
                0.0,
                min(
                    1.0,
                    (available_compute / target["power_watts"])
                    / self.REFERENCE_TFLOPS_PER_WATT,
                ),
            ),
            "locality": (
                1.0
                if workload.get("locality")
                and target.get("locality") == workload.get("locality")
                else 0.0
            ),
            "cost_headroom": max(0.0, 1.0 - target["cost_per_hour"] / budget),
        }
        score = sum(self.WEIGHTS[name] * value for name, value in components.items())
        return round(score, 6), {
            name: round(value, 6) for name, value in components.items()
        }

    def evaluate(
        self,
        req: HeterogeneousPlacementContractRequest,
    ) -> HeterogeneousPlacementContractReceipt:
        reasons: list[str] = []
        if not str(req.subject_id or "").strip():
            reasons.append("subject_id_missing")

        try:
            budget = float(req.budget)
            if budget <= self.MIN_BUDGET:
                reasons.append("budget_non_positive")
        except (TypeError, ValueError):
            budget = 0.0
            reasons.append("budget_invalid")

        if req.grant_id is not None and not str(req.grant_id).strip():
            reasons.append("grant_id_blank")
        if req.not_after is not None:
            try:
                deadline = float(req.not_after)
                now = float(req.now) if req.now is not None else time.time()
                if now > deadline:
                    reasons.append("grant_expired")
            except (TypeError, ValueError):
                reasons.append("not_after_invalid")

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
        for index, raw in enumerate(raw_targets):
            target, errors = self._normalize_target(raw, index)
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
        if workload is not None and budget > 0:
            for target in targets:
                failures = self._feasibility(workload, target, budget)
                if failures:
                    rejected[target["id"]] = tuple(failures)
                    continue
                score, components = self._score(workload, target, budget)
                ranked.append(
                    {
                        "target_id": target["id"],
                        "score": score,
                        "components": components,
                        "available_compute_tflops": round(
                            target["compute_tflops"] * (1.0 - target["utilization"]),
                            6,
                        ),
                        "available_memory_gb": target["available_memory_gb"],
                        "latency_ms": target["latency_ms"],
                        "power_watts": target["power_watts"],
                        "cost_per_hour": target["cost_per_hour"],
                    }
                )

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
                "cost_per_hour": winner["cost_per_hour"],
                "workload": workload,
            }
            reasons = ["placement_selected"]

        digest_body = {
            "schema": "glaciereq.heterogeneous-placement.v2",
            "subject_id": req.subject_id,
            "budget": budget,
            "grant_id": req.grant_id,
            "not_after": req.not_after,
            "workload": workload,
            "targets": sorted(targets, key=lambda target: target["id"]),
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
            "selected_cost_per_hour": ranked[0]["cost_per_hour"] if ranked else None,
            "budget": budget,
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


def request_from_mapping(value: Mapping[str, Any]) -> HeterogeneousPlacementContractRequest:
    raw_payload = value.get("payload")
    if raw_payload is None:
        payload = {
            "workload": value.get("workload"),
            "targets": value.get("targets", []),
        }
    elif isinstance(raw_payload, Mapping):
        payload = dict(raw_payload)
    else:
        raise ValueError("payload must be a JSON object")

    grant_id = value.get("grant_id")
    not_after = value.get("not_after")
    now = value.get("now")
    return HeterogeneousPlacementContractRequest(
        subject_id=str(value.get("subject_id", "")),
        payload=payload,
        budget=float(value.get("budget", 1.0)),
        grant_id=str(grant_id) if grant_id is not None else None,
        not_after=float(not_after) if not_after is not None else None,
        now=float(now) if now is not None else None,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hetero-place",
        description="Deterministically place a workload on feasible heterogeneous compute",
    )
    parser.add_argument("--input", type=Path, help="request JSON file; stdin when omitted")
    parser.add_argument("--output", type=Path, help="optional receipt JSON destination")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    raw = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, Mapping):
            raise ValueError("request must be a JSON object")
        request = request_from_mapping(parsed)
        receipt = HeterogeneousPlacementContract().evaluate(request)
        output = receipt.as_dict()
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        output = {
            "decision": Decision.REFUSE.value,
            "reasons": [f"invalid_request:{exc}"],
            "digest": "",
            "metrics": {},
            "placement": {},
            "ranked_candidates": [],
            "rejected_targets": {},
        }
        encoded = json.dumps(output, indent=2 if args.pretty else None, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 2

    encoded = json.dumps(output, indent=2 if args.pretty else None, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if receipt.decision is Decision.ALLOW else 2


if __name__ == "__main__":
    raise SystemExit(main())
