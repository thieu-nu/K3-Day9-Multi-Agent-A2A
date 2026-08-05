from __future__ import annotations

from decimal import Decimal

from agents.base import error_result, success_result
from agents.coordinator import AgentName, AgentResult, AgentStatus, AgentTask, EntityCandidates
from agents.domain_utils import money_value, parse_money, parse_sequence, parse_timestamp, unique
from utils.data_loader import DataIntegrityError, OlistDataLoader


class OrderSellerAgent:
    def __init__(self, data: OlistDataLoader) -> None:
        self._data = data

    def run(self, task: AgentTask) -> AgentResult:
        lookup_order_id = task.payload.get("lookup_order_id")
        include_products = task.payload.get("include_product_validation", False)
        if lookup_order_id != task.order_id or not isinstance(include_products, bool):
            return error_result(
                task,
                AgentName.ORDER_SELLER,
                status=AgentStatus.INVALID_INPUT,
                code="INVALID_AGENT_PAYLOAD",
                message="lookup_order_id or include_product_validation is invalid",
                source="order_seller",
                path="payload",
            )

        try:
            order = self._data.get_order(task.order_id)
        except DataIntegrityError as exc:
            return self._data_error(task, str(exc), "olist_orders_dataset.csv")
        if order is None:
            return error_result(
                task,
                AgentName.ORDER_SELLER,
                status=AgentStatus.NOT_FOUND,
                code="ORDER_NOT_FOUND",
                message="order does not exist in the database",
                source="olist_orders_dataset.csv",
                path="order_id",
            )

        raw_items = self._data.get_items(task.order_id)
        try:
            carrier_date = parse_timestamp(order.get("order_delivered_carrier_date"))
            item_rows: list[dict[str, object]] = []
            item_ids: list[str] = []
            seller_ids: list[str] = []
            evidence = [f"order:{task.order_id}"]
            item_total = Decimal("0")
            freight_total = Decimal("0")
            seen_item_ids: set[int] = set()
            missing_sellers: list[str] = []
            missing_products: list[str] = []
            violating_sellers: list[str] = []

            parsed_items = sorted(
                (
                    (parse_sequence(row.get("order_item_id"), field="order_item_id"), row)
                    for row in raw_items
                ),
                key=lambda pair: pair[0],
            )
            for sequence, row in parsed_items:
                if sequence in seen_item_ids:
                    raise DataIntegrityError(
                        f"duplicate order_item_id for {task.order_id}: {sequence}"
                    )
                seen_item_ids.add(sequence)
                seller_id = row.get("seller_id")
                product_id = row.get("product_id")
                if not seller_id or not self._data.seller_exists(seller_id):
                    missing_sellers.append(seller_id or "<missing>")
                if include_products and (
                    not product_id or not self._data.product_exists(product_id)
                ):
                    missing_products.append(product_id or "<missing>")

                price = parse_money(row.get("price"), field="price")
                freight = parse_money(row.get("freight_value"), field="freight_value")
                shipping_limit = parse_timestamp(row.get("shipping_limit_date"))
                handoff_after_limit = (
                    carrier_date > shipping_limit
                    if carrier_date is not None and shipping_limit is not None
                    else None
                )
                item_total += price
                freight_total += freight
                item_identity = f"{task.order_id}:{sequence}"
                item_ids.append(item_identity)
                evidence.append(f"item:{item_identity}")
                if seller_id:
                    seller_ids.append(seller_id)
                if handoff_after_limit and seller_id:
                    violating_sellers.append(seller_id)
                item_rows.append(
                    {
                        "order_item_id": sequence,
                        "product_id": product_id,
                        "seller_id": seller_id,
                        "shipping_limit_date": row.get("shipping_limit_date"),
                        "price_brl": money_value(price),
                        "freight_value_brl": money_value(freight),
                        "handoff_after_limit": handoff_after_limit,
                    }
                )
        except (DataIntegrityError, ValueError) as exc:
            return self._data_error(task, str(exc), "olist_order_items_dataset.csv")

        if missing_sellers:
            return self._data_error(
                task,
                f"missing seller references: {', '.join(unique(missing_sellers))}",
                "olist_sellers_dataset.csv",
            )
        if missing_products:
            return self._data_error(
                task,
                f"missing product references: {', '.join(unique(missing_products))}",
                "olist_products_dataset.csv",
            )

        unique_sellers = unique(seller_ids)
        evidence.extend(f"seller:{seller_id}" for seller_id in unique_sellers)
        facts = {
            "order_found": True,
            "order": {name: value for name, value in order.items()},
            "items": item_rows,
            "item_total_brl": money_value(item_total),
            "freight_total_brl": money_value(freight_total),
            "violating_seller_ids": unique(violating_sellers),
            "missing_seller_ids": [],
        }
        return success_result(
            task,
            AgentName.ORDER_SELLER,
            facts=facts,
            entities=EntityCandidates(
                order_ids=[task.order_id],
                item_ids=item_ids,
                seller_ids=unique_sellers,
            ),
            evidence=evidence,
        )

    @staticmethod
    def _data_error(task: AgentTask, message: str, source: str) -> AgentResult:
        return error_result(
            task,
            AgentName.ORDER_SELLER,
            status=AgentStatus.DATA_ERROR,
            code="DATA_INTEGRITY_ERROR",
            message=message,
            source=source,
        )
