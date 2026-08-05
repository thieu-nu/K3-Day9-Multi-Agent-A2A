from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Dict, Any, List, Set
from utils.data_loader import OlistDataLoader

class PaymentAgent:
    """
    Agent nghiệp vụ chịu trách nhiệm điều tra, tính toán và đối soát
    các khoản thanh toán của đơn hàng từ dataset Olist.
    """
    def __init__(self, data_loader: OlistDataLoader):
        self.data_loader = data_loader

    def _quantize_brl(self, val: Decimal | str | float | int) -> Decimal:
        if not isinstance(val, Decimal):
            val = Decimal(str(val))
        return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _create_base_result(self, task: Dict[str, Any], status: str = "success") -> Dict[str, Any]:
        return {
            "contract_version": task.get("contract_version", "1.0"),
            "run_id": task.get("run_id", ""),
            "correlation_id": task.get("correlation_id", ""),
            "case_id": task.get("case_id", ""),
            "order_id": task.get("order_id", ""),
            "agent_name": "payment_agent",
            "status": status,
            "facts": {},
            "entity_candidates": {"payment_ids": []},
            "evidence_candidates": [],
            "warnings": [],
            "errors": []
        }

    def _make_error(self, code: str, path: str, message: str, source: str = "olist_order_payments_dataset.csv") -> Dict[str, Any]:
        return {
            "code": code,
            "path": path,
            "message": message,
            "source": source,
            "retryable": False,
            "retry_target": "coordinator"
        }

    def process_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        result = self._create_base_result(task)
        
        # 1. Kiểm tra bao bì hợp đồng (Envelope Validation)
        if task.get("contract_version") != "1.0":
            result["status"] = "invalid_input"
            result["errors"].append(self._make_error("INVALID_CONTRACT_VERSION", "contract_version", "Chỉ hỗ trợ version 1.0"))
            return result
            
        if task.get("policy_version") != "EC_POLICY_V1":
            result["status"] = "invalid_input"
            result["errors"].append(self._make_error("INVALID_POLICY_VERSION", "policy_version", "Chỉ chấp nhận EC_POLICY_V1"))
            return result

        order_id = str(task.get("order_id", "")).strip()
        payload = task.get("payload", {})
        lookup_order_id = str(payload.get("lookup_order_id", order_id)).strip()
        
        if not order_id or order_id != lookup_order_id:
            result["status"] = "invalid_input"
            result["errors"].append(self._make_error("ORDER_ID_MISMATCH", "payload.lookup_order_id", "order_id trong payload không khớp với envelope"))
            return result

        tolerance_val = payload.get("reconciliation_tolerance_brl", 0.10)
        try:
            tolerance = self._quantize_brl(tolerance_val)
        except InvalidOperation:
            tolerance = Decimal("0.10")

        # 2. Truy xuất dữ liệu thanh toán và sản phẩm (không join)
        payment_rows = self.data_loader.get_order_payments(order_id)
        item_rows = self.data_loader.get_order_items(order_id)

        # 3. Sắp xếp ổn định theo payment_sequential và tính toán
        try:
            sorted_payments = sorted(payment_rows, key=lambda x: int(x.get("payment_sequential", 0)))
        except ValueError:
            sorted_payments = payment_rows

        payments_list: List[Dict[str, Any]] = []
        payment_ids: List[str] = []
        evidence_ids: List[str] = []
        seen_sequentials: Set[int] = set()
        
        payment_total_dec = Decimal("0.00")

        for row in sorted_payments:
            # Kiểm tra lỗi cú pháp và parse sequential
            try:
                seq = int(row.get("payment_sequential", 0))
                inst = int(row.get("payment_installments", 1))
            except ValueError:
                result["status"] = "data_error"
                result["errors"].append(self._make_error("INVALID_SEQUENTIAL_OR_INSTALLMENTS", "payment_sequential", "Số thứ tự hoặc kỳ hạn thanh toán không hợp lệ"))
                return result

            # Trường hợp biên: Trùng payment_sequential trong cùng order
            if seq in seen_sequentials:
                result["status"] = "data_error"
                result["errors"].append(self._make_error("DUPLICATE_PAYMENT_SEQUENTIAL", f"payments[{seq}]", f"Trùng lặp payment_sequential {seq} trong order {order_id}"))
                return result
            seen_sequentials.add(seq)

            # Trường hợp biên: Giá trị tiền không parse được
            try:
                val_dec = self._quantize_brl(row.get("payment_value", "0"))
            except (InvalidOperation, ValueError, TypeError):
                result["status"] = "data_error"
                result["errors"].append(self._make_error("INVALID_PAYMENT_VALUE", f"payments[{seq}].payment_value", f"Giá trị tiền không parse được thành số thập phân"))
                return result

            # Trường hợp biên: Giá trị tiền âm bất thường
            if val_dec < Decimal("0.00"):
                result["status"] = "data_error"
                result["errors"].append(self._make_error("NEGATIVE_PAYMENT_VALUE", f"payments[{seq}].payment_value", f"Giá trị tiền thanh toán âm bất thường: {val_dec}"))
                return result

            payment_total_dec += val_dec
            p_type = str(row.get("payment_type", "unknown"))
            
            payments_list.append({
                "payment_sequential": seq,
                "payment_type": p_type,
                "payment_installments": inst,
                "payment_value_brl": float(val_dec)
            })

            pid = f"{order_id}:{seq}"
            if pid not in payment_ids:
                payment_ids.append(pid)
            
            ev_id = f"payment:{order_id}:{seq}"
            if ev_id not in evidence_ids:
                evidence_ids.append(ev_id)

        # 4. Tính toán chéo tiền hàng (item) và cước (freight) từ items
        item_total_dec = Decimal("0.00")
        freight_total_dec = Decimal("0.00")

        for i_row in item_rows:
            try:
                price_dec = self._quantize_brl(i_row.get("price", "0"))
                freight_dec = self._quantize_brl(i_row.get("freight_value", "0"))
            except (InvalidOperation, TypeError, ValueError):
                result["status"] = "data_error"
                result["errors"].append(self._make_error("INVALID_ITEM_PRICE_OR_FREIGHT", "order_items", "Giá trị tiền hàng hoặc phí ship không hợp lệ", source="olist_order_items_dataset.csv"))
                return result

            item_total_dec += price_dec
            freight_total_dec += freight_dec

        # Làm tròn theo quy tắc ROUND_HALF_UP sau khi tính tổng
        payment_total_dec = self._quantize_brl(payment_total_dec)
        item_total_dec = self._quantize_brl(item_total_dec)
        freight_total_dec = self._quantize_brl(freight_total_dec)

        # Trường hợp biên: Kiểm tra xung đột đối chiếu chéo (conflict) nếu Coordinator gửi thông số từ Order & Seller Agent
        expected_seller_item = payload.get("order_seller_item_total_brl", payload.get("expected_item_total_brl"))
        if expected_seller_item is not None:
            try:
                exp_item_dec = self._quantize_brl(expected_seller_item)
                if abs(item_total_dec - exp_item_dec) > Decimal("0.00"):
                    result["status"] = "conflict"
                    result["errors"].append(self._make_error("CROSS_CHECK_CONFLICT", "item_total_brl_check", f"Tổng item_total_brl_check ({item_total_dec}) không khớp với đối chiếu Order & Seller ({exp_item_dec})"))
                    return result
            except InvalidOperation:
                pass

        expected_seller_freight = payload.get("order_seller_freight_total_brl", payload.get("expected_freight_total_brl"))
        if expected_seller_freight is not None:
            try:
                exp_freight_dec = self._quantize_brl(expected_seller_freight)
                if abs(freight_total_dec - exp_freight_dec) > Decimal("0.00"):
                    result["status"] = "conflict"
                    result["errors"].append(self._make_error("CROSS_CHECK_CONFLICT", "freight_total_brl_check", f"Tổng freight_total_brl_check ({freight_total_dec}) không khớp với đối chiếu Order & Seller ({exp_freight_dec})"))
                    return result
            except InvalidOperation:
                pass

        expected_total_dec = self._quantize_brl(item_total_dec + freight_total_dec)
        difference_dec = self._quantize_brl(abs(payment_total_dec - expected_total_dec))

        is_reconciled = difference_dec <= tolerance
        is_split_payment = len(payment_rows) >= 2

        # 5. Lắp ráp facts và các candidates theo hợp đồng
        result["facts"] = {
            "payments": payments_list,
            "payment_count": len(payment_rows),
            "payment_total_brl": float(payment_total_dec),
            "item_total_brl_check": float(item_total_dec),
            "freight_total_brl_check": float(freight_total_dec),
            "expected_total_brl": float(expected_total_dec),
            "difference_brl": float(difference_dec),
            "is_reconciled": bool(is_reconciled),
            "is_split_payment": bool(is_split_payment)
        }

        # Giới hạn số lượng đầu ra theo mục 11.1 & 11.2 (tối đa 5 entity, 10 evidence)
        result["entity_candidates"] = {"payment_ids": payment_ids[:5]}
        result["evidence_candidates"] = evidence_ids[:10]

        return result
