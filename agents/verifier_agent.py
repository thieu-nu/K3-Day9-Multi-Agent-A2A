from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from agents.base import success_result
from agents.coordinator import (
    AgentError,
    AgentName,
    AgentResult,
    AgentTask,
    CaseInput,
    EvidenceBundle,
    FinalOutput,
    PolicyDecision,
)
from agents.domain_utils import money_value, parse_money, parse_sequence
from agents.policy_agent import PolicyAgent
from utils.data_loader import DataIntegrityError, OlistDataLoader

CHECK_NAMES = ("schema", "identity", "entities", "evidence", "financials", "policy", "limits")


class VerifierAgent:
    def __init__(self, data: OlistDataLoader) -> None:
        self._data = data
        self._policy = PolicyAgent()

    def run(self, task: AgentTask) -> AgentResult:
        checks = {name: True for name in CHECK_NAMES}
        errors: list[AgentError] = []
        draft_version = self._positive_int(task.payload.get("draft_version"), default=1)
        supplied_digest = task.payload.get("draft_digest")
        draft_digest: str = (
            supplied_digest
            if isinstance(supplied_digest, str) and self._is_digest(supplied_digest)
            else "0" * 64
        )

        try:
            case = CaseInput.model_validate(task.payload.get("case_input"))
            bundle = EvidenceBundle.model_validate(task.payload.get("evidence_bundle"))
            decision = PolicyDecision.model_validate(task.payload.get("policy_decision"))
            draft = FinalOutput.model_validate(task.payload.get("draft_output"))
            raw_results = task.payload.get("agent_results")
            if not isinstance(raw_results, dict):
                raise ValueError("agent_results must be an object")
            domain_results = {
                name: AgentResult.model_validate(value) for name, value in raw_results.items()
            }
        except (ValidationError, ValueError, TypeError) as exc:
            checks["schema"] = False
            errors.append(
                self._error(
                    "SCHEMA_VIOLATION",
                    str(exc),
                    AgentName.COORDINATOR,
                    path="payload",
                )
            )
            return self._result(task, draft_version, draft_digest, checks, errors, {})

        actual_digest = self._digest(draft.model_dump(mode="json"))
        identity_ok = (
            case.case_id == task.case_id
            and case.customer_request.claimed_order_id == task.order_id
            and bundle.case_id == task.case_id
            and bundle.order_id == task.order_id
            and decision.bundle_version == bundle.bundle_version
            and decision.bundle_digest == bundle.bundle_digest
            and draft.case_id == task.case_id
            and draft_digest == actual_digest
            and all(
                result.case_id == task.case_id
                and result.order_id == task.order_id
                and result.run_id == task.run_id
                and result.correlation_id == task.correlation_id
                for result in domain_results.values()
            )
        )
        if not identity_ok:
            checks["identity"] = False
            errors.append(
                self._error(
                    "HANDOFF_IDENTITY_MISMATCH",
                    "case, bundle, decision, draft, or digest identity is inconsistent",
                    AgentName.COORDINATOR,
                )
            )

        recomputed: dict[str, Decimal] = {}
        try:
            order = self._data.get_order(task.order_id)
            if order is None:
                raise DataIntegrityError(f"order not found: {task.order_id}")
            items = self._data.get_items(task.order_id)
            payments = self._data.get_payments(task.order_id)
            item_total = sum(
                (parse_money(row.get("price"), field="price") for row in items),
                start=Decimal("0"),
            )
            freight_total = sum(
                (parse_money(row.get("freight_value"), field="freight_value") for row in items),
                start=Decimal("0"),
            )
            payment_total = sum(
                (parse_money(row.get("payment_value"), field="payment_value") for row in payments),
                start=Decimal("0"),
            )
            recomputed = {
                "item_total_brl": Decimal(str(money_value(item_total))),
                "freight_total_brl": Decimal(str(money_value(freight_total))),
                "payment_total_brl": Decimal(str(money_value(payment_total))),
                "recommended_refund_brl": Decimal(
                    str(draft.financial_resolution.recommended_refund_brl)
                ),
            }
        except (DataIntegrityError, ValueError) as exc:
            checks["entities"] = False
            checks["financials"] = False
            errors.append(self._error("DATA_INTEGRITY_ERROR", str(exc), AgentName.ORDER_SELLER))
            return self._result(task, draft_version, draft_digest, checks, errors, recomputed)

        expected_item_ids = {
            f"{task.order_id}:{parse_sequence(row.get('order_item_id'), field='order_item_id')}"
            for row in items
        }
        expected_payment_ids = {
            f"{task.order_id}:"
            f"{parse_sequence(row.get('payment_sequential'), field='payment_sequential')}"
            for row in payments
        }
        expected_sellers = {row["seller_id"] for row in items if row.get("seller_id")}
        entities = draft.affected_entities
        expected_entities = {
            "order_ids": bundle.entity_candidates.order_ids[:5],
            "item_ids": bundle.entity_candidates.item_ids[:5],
            "seller_ids": bundle.entity_candidates.seller_ids[:5],
            "payment_ids": bundle.entity_candidates.payment_ids[:5],
        }
        entities_ok = (
            entities.model_dump(mode="json") == expected_entities
            and set(entities.order_ids).issubset({task.order_id})
            and set(entities.item_ids).issubset(expected_item_ids)
            and set(entities.payment_ids).issubset(expected_payment_ids)
            and set(entities.seller_ids).issubset(expected_sellers)
            and all(self._data.seller_exists(value) for value in entities.seller_ids)
        )
        if not entities_ok:
            checks["entities"] = False
            errors.append(
                self._error(
                    "INVALID_ENTITY_SELECTION",
                    "one or more affected entities do not belong to the order",
                    AgentName.POLICY,
                )
            )

        valid_evidence = {
            f"order:{task.order_id}",
            *(f"item:{identity}" for identity in expected_item_ids),
            *(f"payment:{identity}" for identity in expected_payment_ids),
            *(f"seller:{seller_id}" for seller_id in expected_sellers),
            *(f"policy:{cause.cause_code.value}" for cause in decision.ranked_causes),
        }
        if not set(draft.evidence_ids).issubset(valid_evidence):
            checks["evidence"] = False
            errors.append(
                self._error(
                    "INVALID_EVIDENCE", "draft contains nonexistent evidence", AgentName.POLICY
                )
            )

        financial = draft.financial_resolution
        financial_ok = (
            Decimal(str(financial.item_total_brl)) == recomputed["item_total_brl"]
            and Decimal(str(financial.freight_total_brl)) == recomputed["freight_total_brl"]
            and Decimal(str(financial.payment_total_brl)) == recomputed["payment_total_brl"]
        )
        if not items:
            financial_ok = (
                financial_ok
                and entities.item_ids == []
                and entities.seller_ids == []
                and financial.item_total_brl == 0.0
                and financial.freight_total_brl == 0.0
            )
        if not financial_ok:
            checks["financials"] = False
            errors.append(
                self._error(
                    "FINANCIAL_MISMATCH",
                    "draft totals do not match independent CSV aggregation",
                    AgentName.PAYMENT,
                )
            )

        policy_task = task.model_copy(
            update={
                "payload": {
                    "evidence_bundle": bundle.model_dump(mode="json"),
                    "policy_version": task.policy_version,
                }
            }
        )
        expected_policy_result = self._policy.run(policy_task)
        policy_ok = False
        policy_mismatches: list[str] = []
        if expected_policy_result.status.value == "success":
            expected_decision = PolicyDecision.model_validate(expected_policy_result.facts)
            comparisons = {
                "matched_rule_priority": decision.matched_rule_priority
                == expected_decision.matched_rule_priority,
                "primary_issue": decision.primary_issue == expected_decision.primary_issue,
                "case_status": decision.case_status == expected_decision.case_status,
                "ranked_causes": decision.ranked_causes == expected_decision.ranked_causes,
                "responsible_parties": decision.responsible_parties
                == expected_decision.responsible_parties,
                "selected_entities": decision.selected_entities
                == expected_decision.selected_entities,
                "recommended_refund_brl": decision.recommended_refund_brl
                == expected_decision.recommended_refund_brl,
                "resolution_actions": decision.resolution_actions
                == expected_decision.resolution_actions,
                "selected_evidence_ids": decision.selected_evidence_ids
                == expected_decision.selected_evidence_ids,
                "draft": (
                    draft.assessment.primary_issue == decision.primary_issue
                    and draft.assessment.case_status == decision.case_status
                    and draft.assessment.confidence == decision.confidence
                    and draft.affected_entities.model_dump()
                    == decision.selected_entities.model_dump()
                    and draft.root_cause_analysis.ranked_causes == decision.ranked_causes
                    and draft.root_cause_analysis.responsible_parties
                    == decision.responsible_parties
                    and draft.evidence_ids == decision.selected_evidence_ids
                    and Decimal(str(financial.recommended_refund_brl))
                    == decision.recommended_refund_brl
                    and draft.resolution_actions == decision.resolution_actions
                ),
            }
            policy_mismatches = [name for name, matches in comparisons.items() if not matches]
            policy_ok = not policy_mismatches
        else:
            policy_mismatches = ["expected_policy_result"]
        if not policy_ok:
            checks["policy"] = False
            errors.append(
                self._error(
                    "POLICY_MISMATCH",
                    "decision or draft does not match EC_POLICY_V1: "
                    + ", ".join(policy_mismatches),
                    AgentName.POLICY,
                )
            )

        limits_ok = (
            all(
                len(values) <= 5
                for values in (
                    entities.order_ids,
                    entities.item_ids,
                    entities.seller_ids,
                    entities.payment_ids,
                )
            )
            and len(draft.evidence_ids) <= 10
            and len(draft.root_cause_analysis.ranked_causes) <= 3
            and len(draft.root_cause_analysis.responsible_parties) <= 3
            and len(draft.resolution_actions) <= 5
            and 0 <= draft.assessment.confidence <= 1
        )
        if not limits_ok:
            checks["limits"] = False
            errors.append(
                self._error(
                    "OUTPUT_LIMIT_EXCEEDED", "draft exceeds output limits", AgentName.POLICY
                )
            )

        return self._result(task, draft_version, draft_digest, checks, errors, recomputed)

    @staticmethod
    def _result(
        task: AgentTask,
        draft_version: int,
        draft_digest: str,
        checks: dict[str, bool],
        errors: list[AgentError],
        recomputed: dict[str, Decimal],
    ) -> AgentResult:
        return success_result(
            task,
            AgentName.VERIFIER,
            facts={
                "verdict": "FAIL" if errors else "PASS",
                "draft_version": draft_version,
                "draft_digest": draft_digest,
                "checks": checks,
                "recomputed_values": {key: money_value(value) for key, value in recomputed.items()},
                "errors": [error.model_dump(mode="json") for error in errors],
                "warnings": [],
            },
        )

    @staticmethod
    def _error(
        code: str,
        message: str,
        target: AgentName,
        *,
        path: str = "",
    ) -> AgentError:
        return AgentError(
            code=code,
            path=path,
            message=message,
            source=AgentName.VERIFIER.value,
            retryable=True,
            retry_target=target,
        )

    @staticmethod
    def _positive_int(value: object, *, default: int) -> int:
        return (
            value
            if isinstance(value, int) and not isinstance(value, bool) and value > 0
            else default
        )

    @staticmethod
    def _is_digest(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def _digest(value: dict[str, Any]) -> str:
        payload = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
