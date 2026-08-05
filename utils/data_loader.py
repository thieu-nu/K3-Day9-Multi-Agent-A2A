import csv
import os
from typing import List, Dict, Any, Optional
from pathlib import Path

class OlistDataLoader:
    """
    Lớp tải và truy xuất dữ liệu từ các file CSV của Olist.
    Đảm bảo 100% chỉ đọc, không chỉnh sửa hay can thiệp dữ liệu gốc,
    giữ nguyên mọi định danh và giá trị dưới dạng string (chuỗi).
    """
    def __init__(self, data_dir: str | Path = "data"):
        self.data_dir = str(data_dir)
        self._payments_cache: Optional[Dict[str, List[Dict[str, str]]]] = None
        self._items_cache: Optional[Dict[str, List[Dict[str, str]]]] = None

    def _load_payments_if_needed(self) -> None:
        if self._payments_cache is not None:
            return
        
        self._payments_cache = {}
        file_path = os.path.join(self.data_dir, "olist_order_payments_dataset.csv")
        if not os.path.exists(file_path):
            return

        with open(file_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                order_id = str(row.get("order_id", "")).strip()
                if order_id not in self._payments_cache:
                    self._payments_cache[order_id] = []
                self._payments_cache[order_id].append(dict(row))

    def _load_items_if_needed(self) -> None:
        if self._items_cache is not None:
            return
        
        self._items_cache = {}
        file_path = os.path.join(self.data_dir, "olist_order_items_dataset.csv")
        if not os.path.exists(file_path):
            return

        with open(file_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                order_id = str(row.get("order_id", "")).strip()
                if order_id not in self._items_cache:
                    self._items_cache[order_id] = []
                self._items_cache[order_id].append(dict(row))

    def get_order_payments(self, order_id: str) -> List[Dict[str, str]]:
        """
        Trả về danh sách các bản ghi thanh toán theo order_id.
        Nếu không có bản ghi nào, trả về danh sách rỗng [].
        """
        self._load_payments_if_needed()
        if not self._payments_cache:
            return []
        # Trả về danh sách copy nhẹ để tránh caller vô tình chỉnh sửa bộ nhớ cache
        return [dict(row) for row in self._payments_cache.get(str(order_id).strip(), [])]

    def get_order_items(self, order_id: str) -> List[Dict[str, str]]:
        """
        Trả về danh sách các bản ghi sản phẩm (items) thuộc order_id.
        Nếu không có bản ghi nào, trả về danh sách rỗng [].
        """
        self._load_items_if_needed()
        if not self._items_cache:
            return []
        return [dict(row) for row in self._items_cache.get(str(order_id).strip(), [])]
