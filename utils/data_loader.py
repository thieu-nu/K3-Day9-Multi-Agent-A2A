from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

import polars as pl


class DataIntegrityError(RuntimeError):
    """Raised when the CSV database violates an identity invariant."""


Row = dict[str, str | None]


class OlistDataLoader:
    """Read-only, in-memory indexes over the CSV tables used by the agents."""

    ORDER_COLUMNS = (
        "order_id",
        "customer_id",
        "order_status",
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    )
    ITEM_COLUMNS = (
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
        "shipping_limit_date",
        "price",
        "freight_value",
    )
    PAYMENT_COLUMNS = (
        "order_id",
        "payment_sequential",
        "payment_type",
        "payment_installments",
        "payment_value",
    )

    def __init__(self, data_directory: str | Path) -> None:
        self.data_directory = Path(data_directory)
        if not self.data_directory.is_dir():
            raise FileNotFoundError(f"data directory does not exist: {self.data_directory}")

        self._orders = self._group_rows(
            self._read_strings("olist_orders_dataset.csv", self.ORDER_COLUMNS), "order_id"
        )
        self._items = self._group_rows(
            self._read_strings("olist_order_items_dataset.csv", self.ITEM_COLUMNS), "order_id"
        )
        self._payments = self._group_rows(
            self._read_strings("olist_order_payments_dataset.csv", self.PAYMENT_COLUMNS),
            "order_id",
        )
        self._seller_ids = self._read_key_set("olist_sellers_dataset.csv", "seller_id")
        self._product_ids = self._read_key_set("olist_products_dataset.csv", "product_id")

    def get_order(self, order_id: str) -> Row | None:
        rows = self._orders.get(order_id, ())
        if len(rows) > 1:
            raise DataIntegrityError(f"duplicate order_id in orders: {order_id}")
        return dict(rows[0]) if rows else None

    def get_items(self, order_id: str) -> list[Row]:
        return [dict(row) for row in self._items.get(order_id, ())]

    def get_payments(self, order_id: str) -> list[Row]:
        return [dict(row) for row in self._payments.get(order_id, ())]

    def seller_exists(self, seller_id: str) -> bool:
        return seller_id in self._seller_ids

    def product_exists(self, product_id: str) -> bool:
        return product_id in self._product_ids

    def _read_strings(self, filename: str, columns: Iterable[str]) -> pl.DataFrame:
        path = self.data_directory / filename
        if not path.is_file():
            raise FileNotFoundError(f"required database file does not exist: {path}")
        selected = list(columns)
        return pl.read_csv(
            path,
            columns=selected,
            schema_overrides={column: pl.String for column in selected},
            null_values="",
        )

    def _read_key_set(self, filename: str, key: str) -> frozenset[str]:
        frame = self._read_strings(filename, (key,))
        keys = [value for value in frame.get_column(key).to_list() if value]
        if len(keys) != len(set(keys)):
            raise DataIntegrityError(f"duplicate primary key in {filename}: {key}")
        return frozenset(keys)

    @staticmethod
    def _group_rows(frame: pl.DataFrame, key: str) -> dict[str, tuple[Row, ...]]:
        grouped: defaultdict[str, list[Row]] = defaultdict(list)
        for raw_row in frame.iter_rows(named=True):
            row: Row = {
                name: value if isinstance(value, str) else None for name, value in raw_row.items()
            }
            identity = row.get(key)
            if not identity:
                raise DataIntegrityError(f"missing required key {key}")
            grouped[identity].append(row)
        return {identity: tuple(rows) for identity, rows in grouped.items()}
