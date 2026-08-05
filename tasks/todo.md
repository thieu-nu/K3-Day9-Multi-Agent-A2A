## Task 1: Implement Data Loader for Payment & Order Items
- [x] Xây dựng mô-đun tải dữ liệu `OlistDataLoader` trong `utils/data_loader.py` và viết unit test tương ứng trong `tests/test_data_loader.py`.
  - Acceptance criteria:
    - [x] Có hàm tải và lọc riêng biệt rành mạch: `get_order_payments(order_id)` và `get_order_items(order_id)` (hoặc tương tự).
    - [x] Mọi trường ID và giá trị được trả ra an toàn không làm biến đổi hay hư hại kiểu dữ liệu gốc (không tự ý chuyển ID sang int).
    - [x] Không join 2 bảng 1:N với nhau, trả ra hai danh sách riêng biệt.
    - [x] Có thể dựng cơ chế in-memory index theo `order_id` để việc tìm kiếm diễn ra trong O(1) sau lần nạp file đầu tiên mà tuyệt đối không thay đổi hay ghi file vào thư mục `data/`.
  - Verification:
    - [x] Lệnh kiểm thử PASS: `python -m unittest tests/test_data_loader.py -v`
  - Files:
    - `utils/data_loader.py`
    - `tests/test_data_loader.py`
  - Estimated scope: Small (2 files)

## Task 2: Implement Core Payment Agent Logic & Standard Reconciliation
- [x] Xây dựng lớp/hàm chủ lực cho Payment Agent tại `agents/payment_agent.py` xử lý các đơn hàng tiêu chuẩn (đáp ứng đúng theo schema của `AgentTask` và trả ra `AgentResult`).
  - Acceptance criteria:
    - [x] Tính `payment_count` theo số row, không theo installments.
    - [x] Tính `payment_total_brl`, `item_total_brl_check`, `freight_total_brl_check`, `expected_total_brl`, và `difference_brl` bằng `Decimal` với quy tắc `ROUND_HALF_UP`.
    - [x] Quyết định gán `is_reconciled=True` khi `difference_brl <= 0.10` và `is_split_payment=True` khi có từ 2 payment rows trở lên.
    - [x] Sinh đúng các candidate: `payment_ids` dạng `<order_id>:<payment_sequential>` và `evidence_candidates` dạng `payment:<order_id>:<payment_sequential>`.
  - Verification:
    - [x] Lệnh kiểm thử PASS: `python -m unittest tests/test_payment_agent.py -v`
  - Files:
    - `agents/payment_agent.py`
    - `tests/test_payment_agent.py`
  - Estimated scope: Medium (2 files)

## Task 3: Implement Edge Cases & Error Handling for Payment Agent
- [x] Bổ sung cơ chế xử lý hoàn chỉnh các trường hợp biên và báo cáo lỗi có cấu trúc (structured error detail) vào `agents/payment_agent.py`.
  - Acceptance criteria:
    - [x] Trường hợp order không có payment row: Trả `payments=[]`, `payment_count=0`, totals = `0.00`, `status="success"`, không bịa payment ID hay evidence ID.
    - [x] Trường hợp `payment_sequential` bị trùng lặp trong một order: Trả `status="data_error"`, kèm error detail rõ ràng.
    - [x] Trường hợp tiền thanh toán âm hoặc sai format không parse được thành số: Trả `status="data_error"`.
    - [x] Trường hợp sai lệch/xung đột dữ liệu nghiêm trọng theo hợp đồng đối soát: Trả `status="conflict"`.
  - Verification:
    - [x] Lệnh kiểm thử PASS cho toàn bộ test cases cơ bản và biên: `python -m unittest discover -s tests -v`
  - Files:
    - `agents/payment_agent.py`
    - `tests/test_payment_agent.py`
  - Estimated scope: Medium (2 files)
