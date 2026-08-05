# Spec: Payment Agent

## Objective
Triển khai module `Payment Agent` (trong file `agents/payment_agent.py`) và phần đọc dữ liệu tương ứng trong `utils/data_loader.py` theo kiến trúc Multi-Agent A2A (Hệ thống xử lý khiếu nại thương mại điện tử Olist). 
Mục tiêu chính là giúp Payment Agent:
1. Đọc và truy xuất chính xác dữ liệu thanh toán từ `olist_order_payments_dataset.csv` và dữ liệu sản phẩm từ `olist_order_items_dataset.csv` theo `order_id`.
2. Tính toán các con số tài chính (tổng tiền thanh toán, tiền hàng, tiền ship, sai lệch) với độ chính xác tuyệt đối sử dụng kiểu dữ liệu số thập phân (`Decimal`), làm tròn 2 chữ số theo quy tắc `ROUND_HALF_UP`.
3. Đối soát thanh toán (`is_reconciled`) và xác định trạng thái thanh toán chia nhỏ (`is_split_payment`).
4. Xuất ra chuẩn hợp đồng dữ liệu (`AgentResult`) bao gồm `facts`, `entity_candidates`, và `evidence_candidates` hoặc báo cáo lỗi (`data_error`, `conflict`, `not_found`) đúng chuẩn cấu trúc của dự án.

## Tech Stack
- **Ngôn ngữ:** Python 3.11
- **Thư viện chính:** Thư viện chuẩn Python (`csv`, `decimal`, `json`, `pathlib`, `typing`, `dataclasses`). Sử dụng `decimal.Decimal` và `ROUND_HALF_UP` cho mọi phép tính tiền tệ BRL.
- **Thư viện kiểm chứng (Testing):** `pytest` hoặc `unittest` tích hợp sẵn trong Python.

## Commands
```bash
# Lệnh chạy unit test cho Payment Agent và Data Loader
python -m unittest discover -s tests -p "test_payment*.py" -v
# (Hoặc nếu dùng pytest)
pytest tests/test_payment_agent.py -v
```

## Project Structure
```text
project/
│
├── data/                                      # CSV nguồn (chỉ đọc)
│   ├── olist_order_items_dataset.csv
│   └── olist_order_payments_dataset.csv
├── agents/
│   └── payment_agent.py                       # [IMPLEMENT] Nền tảng logic và xử lý của Payment Agent
├── utils/
│   └── data_loader.py                         # [IMPLEMENT/MODIFY] Hàm đọc và truy vấn payment/items theo order_id
├── specs/
│   └── payment_agent_spec.md                  # [NEW] File tài liệu đặc tả (Spec) này
└── tests/
    └── test_payment_agent.py                  # [NEW] Unit tests kiểm chứng Payment Agent và các trường hợp biên
```

## Code Style
- Phụ lục kiểu code theo PEP 8, gợi ý chú giải định nghĩa hàm (Type Hinting) đầy đủ.
- Dùng từ khóa xác thực, rõ ràng, không viết tắt gây nhầm lẫn.
- Mọi ID trong CSV phải được giữ nguyên dạng `str` (chuỗi), không được tự ý biến đổi hay chuyển thành số.

Ví dụ kiểu triển khai hàm đối soát giá trị tiền:
```python
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any

def compute_payment_total(payment_rows: List[Dict[str, str]]) -> Decimal:
    total = Decimal('0.0')
    for row in payment_rows:
        val = Decimal(str(row['payment_value'])).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total += val
    return total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
```

## Testing Strategy
- **Framework:** `unittest` (thư viện chuẩn Python để tránh phụ thuộc môi trường chưa setup) hoặc `pytest`.
- **Vị trí test:** Thư mục `tests/`, file `test_payment_agent.py`.
- **Cấp độ test:**
  - **Unit test cho DataLoader:** Đảm bảo truy vấn chính xác danh sách dict theo `order_id`, không tạo tích Descartes hay nhân bản dữ liệu, giữ nguyên kiểu chuỗi cho ID.
  - **Unit test cho PaymentAgent (Trường hợp chuẩn):** Đối soát thành công khi số tiền thanh toán bằng tiền hàng + phí ship (sai lệch <= 0.10 BRL), nhận diện đúng `is_split_payment`.
  - **Unit test cho Trường hợp biên (Edge Cases theo mục 8.3 & 3.2):**
    - `order_id` không có payment row nào (`payment_count = 0`, `payment_total = 0.00`, không bịa ID).
    - Trùng số thứ tự thanh toán (`payment_sequential` trùng lặp -> `data_error`).
    - Giá trị tiền không parse được hoặc âm bất thường (-> `data_error`).
    - Kiểm tra chéo tổng tiền `item_total + freight_total` bị mâu thuẫn với kết quả expected (-> `conflict` hoặc test kiểm tra sai lệch không khớp nhau).

## Boundaries
- **Always do (Luôn thực hiện):**
  - Tuân theo cấu trúc bao bì `AgentTask` và trả ra đúng cấu trúc `AgentResult`.
  - Giữ toàn bộ ID của dataset là chuỗi (`string`).
  - Lọc riêng `order_payments` và `order_items` rồi tính tổng ĐỘC LẬP (Tuyệt đối không join thô 1:N vì gây tích Descartes).
  - Viết test chứng minh code hoạt động theo chuẩn Test-Driven Development trước hoặc song song lúc implement.
- **Ask first (Hỏi trước khi làm):**
  - Thêm bất kỳ thư viện bên thứ 3 nào ra ngoài standard library vào requirements.
  - Sửa đổi các module hay agent khác không thuộc phạm vi `payment_agent` và phần hỗ trợ trong `data_loader.py`.
- **Never do (Tuyệt đối không):**
  - Không thay đổi hoặc chỉnh sửa nội dung file trong thư mục `data/` (nguồn sự thật chỉ đọc).
  - Không đổi `case_id`, `order_id`, `policy_version`, hay `correlation_id` khi bàn giao dữ liệu.
  - Không tự suy diễn hay phán đoán dữ liệu không có trong file CSV.
  - Không dùng float để tính tiền (phải dùng `Decimal`).

## Success Criteria
1. **Tính chính xác tài chính (Financial Determinism):** Mọi con số tài chính (`payment_total_brl`, `item_total_brl_check`, `freight_total_brl_check`, `expected_total_brl`, `difference_brl`) được tính toán xác thực bằng `Decimal` và khớp 100% với expected totals, không có lỗi làm tròn của float.
2. **Đối soát chuẩn quy tắc (Reconciliation):** Sai lệch $\le 0.10$ BRL trả về `is_reconciled = True`, lớn hơn $0.10$ trả về `False`. Có $\ge 2$ dòng thanh toán trả về `is_split_payment = True`.
3. **Đúng cấu trúc hợp đồng (Contract Compliance):** Đầu ra của Agent đúng schema `AgentResult` (mục 6.3 trong architecture.md), danh sách `evidence_candidates` mang định dạng `payment:<order_id>:<payment_sequential>` và `entity_candidates` có cấu trúc rõ ràng.
4. **Xử lý toàn diện trường hợp biên:** Mọi edge case (trùng sequential, giá trị âm/lỗi parse, order không có payment) được test và trả về đúng mã `status` (`data_error`, v.v.).

## Open Questions
- Không có open questions kỹ thuật cản trở. Hiện mặc định sử dụng thư viện chuẩn Python (`unittest`, `csv`, `decimal`) để đảm bảo tính độc lập và khả năng tái lập 100%.
