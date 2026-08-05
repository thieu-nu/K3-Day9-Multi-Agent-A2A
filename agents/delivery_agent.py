from __future__ import annotations

from agents.base import error_result, success_result
from agents.coordinator import AgentName, AgentResult, AgentStatus, AgentTask, EntityCandidates
from agents.domain_utils import parse_sequence, parse_timestamp, unique
from utils.data_loader import DataIntegrityError, OlistDataLoader


class DeliveryAgent:
    def __init__(self, data: OlistDataLoader) -> None:
        self._data = data

    def run(self, task: AgentTask) -> AgentResult:
        if task.payload.get("lookup_order_id") != task.order_id:
            return error_result(
                task,
                AgentName.DELIVERY,
                status=AgentStatus.INVALID_INPUT,
                code="INVALID_AGENT_PAYLOAD",
                message="lookup_order_id does not match task order_id",
                source="delivery",
                path="payload.lookup_order_id",
            )
        try:
            order = self._data.get_order(task.order_id)
        except DataIntegrityError as exc:
            return self._data_error(task, str(exc), "olist_orders_dataset.csv")
        if order is None:
            return error_result(
                task,
                AgentName.DELIVERY,
                status=AgentStatus.NOT_FOUND,
                code="ORDER_NOT_FOUND",
                message="order does not exist in the database",
                source="olist_orders_dataset.csv",
            )

        try:
            carrier_date = parse_timestamp(order.get("order_delivered_carrier_date"))
            delivered_date = parse_timestamp(order.get("order_delivered_customer_date"))
            estimated_date = parse_timestamp(order.get("order_estimated_delivery_date"))
            handoffs: list[dict[str, object]] = []
            seller_ids: list[str] = []
            item_ids: list[str] = []
            seen_sequences: set[int] = set()
            parsed_items = sorted(
                (
                    (parse_sequence(row.get("order_item_id"), field="order_item_id"), row)
                    for row in self._data.get_items(task.order_id)
                ),
                key=lambda pair: pair[0],
            )
            for sequence, row in parsed_items:
                if sequence in seen_sequences:
                    raise DataIntegrityError(
                        f"duplicate order_item_id for {task.order_id}: {sequence}"
                    )
                seen_sequences.add(sequence)
                shipping_limit = parse_timestamp(row.get("shipping_limit_date"))
                handoff_after_limit = (
                    carrier_date > shipping_limit
                    if carrier_date is not None and shipping_limit is not None
                    else None
                )
                seller_id = row.get("seller_id")
                if seller_id:
                    seller_ids.append(seller_id)
                item_ids.append(f"{task.order_id}:{sequence}")
                handoffs.append(
                    {
                        "order_item_id": sequence,
                        "seller_id": seller_id,
                        "shipping_limit_date": row.get("shipping_limit_date"),
                        "carrier_date": order.get("order_delivered_carrier_date"),
                        "handoff_after_limit": handoff_after_limit,
                    }
                )
        except (DataIntegrityError, ValueError) as exc:
            return self._data_error(
                task, str(exc), "olist_orders_dataset.csv/olist_order_items_dataset.csv"
            )

        timestamps_available = delivered_date is not None and estimated_date is not None
        if delivered_date is not None and estimated_date is not None:
            delivered_after = delivered_date > estimated_date
            delivered_within = delivered_date <= estimated_date
        else:
            delivered_after = False
            delivered_within = False
        late_sellers = unique(
            [
                str(handoff["seller_id"])
                for handoff in handoffs
                if handoff["handoff_after_limit"] is True and handoff["seller_id"]
            ]
        )
        warnings: list[str | dict[str, object]] = []
        order_status = order.get("order_status")
        if order_status in {"canceled", "unavailable"}:
            attribution = "not_applicable"
            causes: list[str] = []
        elif not timestamps_available:
            attribution = "unknown"
            causes = []
            warnings.append("delivery timestamp or estimate is missing")
        elif delivered_within:
            attribution = "none"
            causes = ["DELIVERY_WITHIN_ESTIMATE"]
        elif late_sellers:
            attribution = "seller"
            causes = ["SELLER_HANDOFF_AFTER_LIMIT"]
        elif handoffs and all(handoff["handoff_after_limit"] is False for handoff in handoffs):
            attribution = "logistics_provider"
            causes = ["CARRIER_DELIVERED_AFTER_ESTIMATE"]
        else:
            attribution = "unknown"
            causes = []
            warnings.append("seller handoff timestamps are incomplete")

        unique_sellers = unique(seller_ids)
        return success_result(
            task,
            AgentName.DELIVERY,
            facts={
                "delivery_timestamp_available": timestamps_available,
                "delivered_after_estimate": delivered_after,
                "delivery_within_estimate": delivered_within,
                "seller_handoffs": handoffs,
                "attribution_candidate": attribution,
                "responsible_seller_candidates": late_sellers,
                "root_cause_candidates": causes,
            },
            entities=EntityCandidates(
                order_ids=[task.order_id], item_ids=item_ids, seller_ids=unique_sellers
            ),
            evidence=[
                f"order:{task.order_id}",
                *(f"item:{identity}" for identity in item_ids),
                *(f"seller:{seller_id}" for seller_id in unique_sellers),
            ],
            warnings=warnings,
        )

    @staticmethod
    def _data_error(task: AgentTask, message: str, source: str) -> AgentResult:
        return error_result(
            task,
            AgentName.DELIVERY,
            status=AgentStatus.DATA_ERROR,
            code="DATA_INTEGRITY_ERROR",
            message=message,
            source=source,
        )
