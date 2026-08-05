from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from agents.base import error_result, success_result
from agents.coordinator import (
    AgentName,
    AgentResult,
    AgentStatus,
    AgentTask,
    EntityCandidates,
    EvidenceBundle,
)
from agents.domain_utils import money_value


class PolicyAgent:
    """Deterministic implementation of the ordered EC_POLICY_V1 rule table."""

    def run(self, task: AgentTask) -> AgentResult:
        if task.payload.get("policy_version") != task.policy_version:
            return self._error(task, "UNSUPPORTED_POLICY_VERSION", "policy version mismatch")
        try:
            bundle = EvidenceBundle.model_validate(task.payload.get("evidence_bundle"))
        except ValidationError as exc:
            return self._error(task, "INVALID_EVIDENCE_BUNDLE", str(exc))
        if (
            bundle.case_id != task.case_id
            or bundle.order_id != task.order_id
            or bundle.policy_version != task.policy_version
        ):
            return self._error(task, "HANDOFF_IDENTITY_MISMATCH", "bundle identity mismatch")

        order = bundle.order_facts
        item_facts = bundle.item_seller_facts
        payment = bundle.payment_facts
        delivery = bundle.delivery_facts
        order_status = order.get("order_status")
        payment_total = self._decimal(payment.get("payment_total_brl"))
        freight_total = self._decimal(item_facts.get("freight_total_brl"))
        payment_count = payment.get("payment_count")
        difference = self._decimal(payment.get("difference_brl"))
        is_reconciled = payment.get("is_reconciled") is True
        delivered_after = delivery.get("delivered_after_estimate") is True
        delivered_within = delivery.get("delivery_within_estimate") is True
        attribution = delivery.get("attribution_candidate")

        rule: dict[str, Any] | None = None
        if order_status == "canceled" and payment_total > 0:
            rule = self._rule(
                1,
                "canceled_order_paid",
                "ORDER_CANCELED_AFTER_PAYMENT",
                "action_required",
                payment_total,
                "issue_full_refund",
                [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}],
            )
        elif order_status == "unavailable" and payment_total > 0:
            rule = self._rule(
                2,
                "unavailable_order_paid",
                "ORDER_UNAVAILABLE_AFTER_PAYMENT",
                "action_required",
                payment_total,
                "issue_full_refund",
                [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}],
            )
        elif delivered_after and attribution == "seller":
            sellers = list(delivery.get("responsible_seller_candidates", []))
            if not sellers:
                return self._error(task, "MISSING_CRITICAL_FACT", "late seller IDs are missing")
            rule = self._rule(
                3,
                "late_delivery_seller",
                "SELLER_HANDOFF_AFTER_LIMIT",
                "action_required",
                freight_total,
                "refund_freight",
                [{"party_type": "seller", "party_id": seller_id} for seller_id in sellers[:3]],
            )
        elif delivered_after and attribution == "logistics_provider":
            rule = self._rule(
                4,
                "late_delivery_logistics",
                "CARRIER_DELIVERED_AFTER_ESTIMATE",
                "action_required",
                freight_total,
                "refund_freight",
                [{"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}],
            )
        elif (
            isinstance(payment_count, int) and payment_count >= 2 and difference <= Decimal("0.10")
        ):
            rule = self._rule(
                5,
                "valid_split_payment",
                "MULTIPLE_PAYMENTS_RECONCILED",
                "no_action",
                Decimal("0"),
                "explain_valid_split_payment",
                [],
            )
        elif delivered_within and is_reconciled:
            rule = self._rule(
                6,
                "unsupported_late_claim",
                "DELIVERY_WITHIN_ESTIMATE",
                "no_action",
                Decimal("0"),
                "reject_late_refund",
                [],
            )

        if rule is None:
            return self._error(task, "UNCLASSIFIED_CASE", "no EC_POLICY_V1 rule matched")

        priority = int(rule["matched_rule_priority"])
        cause = str(rule["ranked_causes"][0]["cause_code"])
        selected_entities = self._select_entities(bundle.entity_candidates)
        evidence = self._select_evidence(bundle, priority, cause, delivery)
        if not evidence:
            return self._error(task, "INVALID_EVIDENCE", "no valid evidence supports the rule")
        facts = {
            "bundle_version": bundle.bundle_version,
            "bundle_digest": bundle.bundle_digest,
            **rule,
            "confidence": 1.0,
            "confidence_basis": ["critical_facts_complete", "rule_match_exact"],
            "selected_entities": selected_entities.model_dump(mode="json"),
            "selected_evidence_ids": evidence,
            "excluded_higher_priority_rules": [
                {"priority": value, "reason_code": "RULE_CONDITION_NOT_MET"}
                for value in range(1, priority)
            ],
        }
        return success_result(task, AgentName.POLICY, facts=facts)

    @staticmethod
    def _rule(
        priority: int,
        issue: str,
        cause: str,
        status: str,
        refund: Decimal,
        action: str,
        parties: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {
            "matched_rule_priority": priority,
            "primary_issue": issue,
            "case_status": status,
            "ranked_causes": [{"cause_code": cause, "rank": 1}],
            "responsible_parties": parties,
            "recommended_refund_brl": money_value(refund),
            "resolution_actions": [action],
        }

    @staticmethod
    def _select_entities(candidates: EntityCandidates) -> EntityCandidates:
        return EntityCandidates(
            order_ids=candidates.order_ids[:5],
            item_ids=candidates.item_ids[:5],
            seller_ids=candidates.seller_ids[:5],
            payment_ids=candidates.payment_ids[:5],
        )

    @staticmethod
    def _select_evidence(
        bundle: EvidenceBundle,
        priority: int,
        cause: str,
        delivery: dict[str, Any],
    ) -> list[str]:
        available = set(bundle.evidence_candidates)
        selected: list[str] = []

        def add(value: str) -> None:
            if value in available and value not in selected and len(selected) < 9:
                selected.append(value)

        add(f"order:{bundle.order_id}")
        if priority in {3, 4, 6}:
            if priority == 3:
                late_sequences = {
                    handoff.get("order_item_id")
                    for handoff in delivery.get("seller_handoffs", [])
                    if handoff.get("handoff_after_limit") is True
                }
                for identity in bundle.entity_candidates.item_ids:
                    try:
                        sequence = int(identity.rsplit(":", 1)[1])
                    except (IndexError, ValueError):
                        continue
                    if sequence in late_sequences:
                        add(f"item:{identity}")
                for seller_id in delivery.get("responsible_seller_candidates", []):
                    add(f"seller:{seller_id}")
            else:
                for identity in bundle.entity_candidates.item_ids:
                    add(f"item:{identity}")
        if priority in {1, 2, 3, 4, 5, 6}:
            for identity in bundle.entity_candidates.payment_ids:
                add(f"payment:{identity}")
        if priority == 5:
            for identity in bundle.entity_candidates.item_ids:
                add(f"item:{identity}")
        selected.append(f"policy:{cause}")
        return selected[:10]

    @staticmethod
    def _decimal(value: object) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except Exception:
            return Decimal("NaN")
        return parsed if parsed.is_finite() else Decimal("NaN")

    @staticmethod
    def _error(task: AgentTask, code: str, message: str) -> AgentResult:
        return error_result(
            task,
            AgentName.POLICY,
            status=AgentStatus.DATA_ERROR,
            code=code,
            message=message,
            source="EC_POLICY_V1",
        )
