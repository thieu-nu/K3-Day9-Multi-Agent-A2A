from __future__ import annotations

from decimal import Decimal, InvalidOperation

from agents.base import error_result, success_result
from agents.coordinator import AgentName, AgentResult, AgentStatus, AgentTask, EntityCandidates
from agents.domain_utils import money_value, parse_money, parse_sequence
from utils.data_loader import DataIntegrityError, OlistDataLoader


class PaymentAgent:
    def __init__(self, data: OlistDataLoader) -> None:
        self._data = data

    def run(self, task: AgentTask) -> AgentResult:
        if task.payload.get("lookup_order_id") != task.order_id:
            return self._invalid_payload(task)
        try:
            tolerance = Decimal(str(task.payload.get("reconciliation_tolerance_brl")))
        except (InvalidOperation, ValueError):
            return self._invalid_payload(task)
        if not tolerance.is_finite() or tolerance < 0:
            return self._invalid_payload(task)

        raw_payments = self._data.get_payments(task.order_id)
        raw_items = self._data.get_items(task.order_id)
        try:
            payments: list[dict[str, object]] = []
            payment_ids: list[str] = []
            payment_total = Decimal("0")
            seen_sequences: set[int] = set()
            parsed_payments = sorted(
                (
                    (parse_sequence(row.get("payment_sequential"), field="payment_sequential"), row)
                    for row in raw_payments
                ),
                key=lambda pair: pair[0],
            )
            for sequence, row in parsed_payments:
                if sequence in seen_sequences:
                    raise DataIntegrityError(
                        f"duplicate payment_sequential for {task.order_id}: {sequence}"
                    )
                seen_sequences.add(sequence)
                value = parse_money(row.get("payment_value"), field="payment_value")
                installments = parse_sequence(
                    row.get("payment_installments"), field="payment_installments"
                )
                payment_total += value
                payment_ids.append(f"{task.order_id}:{sequence}")
                payments.append(
                    {
                        "payment_sequential": sequence,
                        "payment_type": row.get("payment_type"),
                        "payment_installments": installments,
                        "payment_value_brl": money_value(value),
                    }
                )

            item_total = sum(
                (parse_money(row.get("price"), field="price") for row in raw_items),
                start=Decimal("0"),
            )
            freight_total = sum(
                (parse_money(row.get("freight_value"), field="freight_value") for row in raw_items),
                start=Decimal("0"),
            )
        except (DataIntegrityError, ValueError) as exc:
            return error_result(
                task,
                AgentName.PAYMENT,
                status=AgentStatus.DATA_ERROR,
                code="DATA_INTEGRITY_ERROR",
                message=str(exc),
                source="olist_order_payments_dataset.csv/olist_order_items_dataset.csv",
            )

        expected_total = item_total + freight_total
        difference = abs(payment_total - expected_total)
        facts = {
            "payments": payments,
            "payment_count": len(payments),
            "payment_total_brl": money_value(payment_total),
            "item_total_brl_check": money_value(item_total),
            "freight_total_brl_check": money_value(freight_total),
            "expected_total_brl": money_value(expected_total),
            "difference_brl": money_value(difference),
            "is_reconciled": difference <= tolerance,
            "is_split_payment": len(payments) >= 2,
        }
        return success_result(
            task,
            AgentName.PAYMENT,
            facts=facts,
            entities=EntityCandidates(payment_ids=payment_ids),
            evidence=[f"payment:{identity}" for identity in payment_ids],
        )

    @staticmethod
    def _invalid_payload(task: AgentTask) -> AgentResult:
        return error_result(
            task,
            AgentName.PAYMENT,
            status=AgentStatus.INVALID_INPUT,
            code="INVALID_AGENT_PAYLOAD",
            message="lookup_order_id or reconciliation tolerance is invalid",
            source="payment",
            path="payload",
        )
