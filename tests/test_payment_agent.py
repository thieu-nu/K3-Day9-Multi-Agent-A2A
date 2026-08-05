import unittest
import tempfile
import os
import shutil
from decimal import Decimal
from utils.data_loader import OlistDataLoader
from agents.payment_agent import PaymentAgent

class TestPaymentAgentStandard(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        
        # Tạo dữ liệu thanh toán chuẩn
        payments_csv = os.path.join(self.test_dir, "olist_order_payments_dataset.csv")
        with open(payments_csv, "w", encoding="utf-8") as f:
            f.write('"order_id","payment_sequential","payment_type","payment_installments","payment_value"\n')
            f.write('order_reconciled,1,credit_card,1,115.00\n')
            f.write('order_split,1,credit_card,2,50.00\n')
            f.write('order_split,2,voucher,1,50.00\n')
            f.write('order_tolerance,1,boleto,1,100.05\n')
            
        items_csv = os.path.join(self.test_dir, "olist_order_items_dataset.csv")
        with open(items_csv, "w", encoding="utf-8") as f:
            f.write('"order_id","order_item_id","product_id","seller_id","shipping_limit_date","price","freight_value"\n')
            f.write('order_reconciled,1,prod_1,seller_1,2018-01-01 12:00:00,100.00,15.00\n')
            f.write('order_split,1,prod_2,seller_2,2018-01-01 12:00:00,90.00,10.00\n')
            f.write('order_tolerance,1,prod_3,seller_3,2018-01-01 12:00:00,90.00,10.00\n')
            
        self.loader = OlistDataLoader(data_dir=self.test_dir)
        self.agent = PaymentAgent(data_loader=self.loader)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _make_task(self, order_id: str, tolerance: float = 0.10, extra_payload: dict = None) -> dict:
        payload = {
            "lookup_order_id": order_id,
            "reconciliation_tolerance_brl": tolerance
        }
        if extra_payload:
            payload.update(extra_payload)
        return {
            "contract_version": "1.0",
            "run_id": "run_test_01",
            "correlation_id": "corr_test_01",
            "case_id": "EC_001",
            "order_id": order_id,
            "policy_version": "EC_POLICY_V1",
            "requested_at": "2018-10-18T00:00:00-03:00",
            "payload": payload
        }

    def test_standard_reconciled_payment(self):
        task = self._make_task("order_reconciled")
        result = self.agent.process_task(task)
        
        self.assertEqual(result["status"], "success")
        facts = result["facts"]
        self.assertEqual(facts["payment_count"], 1)
        self.assertEqual(facts["payment_total_brl"], 115.00)
        self.assertEqual(facts["item_total_brl_check"], 100.00)
        self.assertEqual(facts["freight_total_brl_check"], 15.00)
        self.assertEqual(facts["expected_total_brl"], 115.00)
        self.assertEqual(facts["difference_brl"], 0.00)
        self.assertTrue(facts["is_reconciled"])
        self.assertFalse(facts["is_split_payment"])
        self.assertEqual(result["entity_candidates"]["payment_ids"], ["order_reconciled:1"])
        self.assertEqual(result["evidence_candidates"], ["payment:order_reconciled:1"])

    def test_split_payment(self):
        task = self._make_task("order_split")
        result = self.agent.process_task(task)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["facts"]["payment_count"], 2)
        self.assertTrue(result["facts"]["is_split_payment"])
        self.assertEqual(result["entity_candidates"]["payment_ids"], ["order_split:1", "order_split:2"])

    def test_reconciliation_within_tolerance(self):
        task = self._make_task("order_tolerance", tolerance=0.10)
        result = self.agent.process_task(task)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["facts"]["is_reconciled"])


class TestPaymentAgentEdgeCases(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        
        payments_csv = os.path.join(self.test_dir, "olist_order_payments_dataset.csv")
        with open(payments_csv, "w", encoding="utf-8") as f:
            f.write('"order_id","payment_sequential","payment_type","payment_installments","payment_value"\n')
            # Trùng payment_sequential
            f.write('order_dup_seq,1,credit_card,1,50.00\n')
            f.write('order_dup_seq,1,voucher,1,20.00\n')
            # Giá trị tiền âm
            f.write('order_neg_val,1,credit_card,1,-10.00\n')
            # Giá trị tiền lỗi chuỗi
            f.write('order_bad_val,1,credit_card,1,abc_value\n')
            # Đơn hàng chuẩn để test xung đột kiểm tra chéo (conflict)
            f.write('order_conflict,1,credit_card,1,100.00\n')
            
        items_csv = os.path.join(self.test_dir, "olist_order_items_dataset.csv")
        with open(items_csv, "w", encoding="utf-8") as f:
            f.write('"order_id","order_item_id","product_id","seller_id","shipping_limit_date","price","freight_value"\n')
            f.write('order_conflict,1,prod_1,seller_1,2018-01-01 12:00:00,80.00,20.00\n')
            
        self.loader = OlistDataLoader(data_dir=self.test_dir)
        self.agent = PaymentAgent(data_loader=self.loader)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _make_task(self, order_id: str, extra_payload: dict = None) -> dict:
        payload = {"lookup_order_id": order_id}
        if extra_payload:
            payload.update(extra_payload)
        return {
            "contract_version": "1.0",
            "run_id": "run_edge_01",
            "correlation_id": "corr_edge_01",
            "case_id": "EC_002",
            "order_id": order_id,
            "policy_version": "EC_POLICY_V1",
            "requested_at": "2018-10-18T00:00:00-03:00",
            "payload": payload
        }

    def test_empty_order_payments(self):
        # Không có payment row: count và total bằng 0, danh sách rỗng; không bịa payment ID
        task = self._make_task("order_no_payment")
        result = self.agent.process_task(task)
        self.assertEqual(result["status"], "success")
        facts = result["facts"]
        self.assertEqual(facts["payment_count"], 0)
        self.assertEqual(facts["payment_total_brl"], 0.00)
        self.assertEqual(facts["payments"], [])
        self.assertEqual(result["entity_candidates"]["payment_ids"], [])
        self.assertEqual(result["evidence_candidates"], [])

    def test_duplicate_payment_sequential(self):
        # Payment sequential trùng trong cùng order: data_error
        task = self._make_task("order_dup_seq")
        result = self.agent.process_task(task)
        self.assertEqual(result["status"], "data_error")
        self.assertEqual(result["facts"], {})
        self.assertGreaterEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["code"], "DUPLICATE_PAYMENT_SEQUENTIAL")

    def test_negative_payment_value(self):
        # Giá trị tiền âm bất thường: data_error
        task = self._make_task("order_neg_val")
        result = self.agent.process_task(task)
        self.assertEqual(result["status"], "data_error")
        self.assertEqual(result["facts"], {})
        self.assertGreaterEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["code"], "NEGATIVE_PAYMENT_VALUE")

    def test_invalid_unparseable_payment_value(self):
        # Giá trị tiền không parse được: data_error
        task = self._make_task("order_bad_val")
        result = self.agent.process_task(task)
        self.assertEqual(result["status"], "data_error")
        self.assertGreaterEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["code"], "INVALID_PAYMENT_VALUE")

    def test_cross_check_conflict_with_order_seller(self):
        # Tổng item/freight kiểm tra chéo khác Order & Seller Agent: trả conflict
        # Gửi kèm tham số đối chiếu trong payload (order_seller_item_total_brl = 999.99 thay vì 80.00)
        task = self._make_task("order_conflict", extra_payload={"order_seller_item_total_brl": 999.99})
        result = self.agent.process_task(task)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["facts"], {})
        self.assertGreaterEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["code"], "CROSS_CHECK_CONFLICT")

if __name__ == "__main__":
    unittest.main()
