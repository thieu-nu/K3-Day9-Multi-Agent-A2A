# Implementation Plan: Payment Agent & Data Loader Support

## Overview
Xây dựng trọn gói module `Payment Agent` trong `agents/payment_agent.py` và phần hàm trợ giúp đọc file của `Data Loader` trong `utils/data_loader.py`, sử dụng ngôn ngữ Python 3.11 với thư viện chuẩn. Kế hoạch tuân thủ mô hình Test-Driven Development (TDD) và triển khai tăng dần (Incremental Implementation), đảm bảo tính toán tiền tệ bằng `Decimal`, giữ nguyên nguồn dữ liệu CSV không qua sửa đổi và trả ra Hợp đồng Dữ liệu (Contract) đúng theo tài liệu kiến trúc.

## Architecture Decisions
- **Thư viện chuẩn Python (Standard Library):** Dùng `csv.DictReader`, `decimal.Decimal`, `json` và `dataclasses`/`typing` nhằm đảm bảo khả năng tái lập 100%, không bị sai lệch kiểu làm tròn số của float và không gây phụ thuộc môi trường bên thứ ba.
- **Cách ly nghiệp vụ Data Loader:** Trong `utils/data_loader.py` xây dựng lớp `OlistDataLoader` (hoặc các hàm đọc độc lập) giúp truy vấn danh sách bản ghi theo `order_id` cho 2 bảng `order_payments` và `order_items` mà không join bảng (tránh tích Descartes) và giữ nguyên toàn bộ định danh dạng `str`.
- **Thiết kế định dạng lỗi Có Cấu Trúc (Structured Error Reporting):** Khi phát hiện lỗi vi phạm dữ liệu (trùng số thứ tự thanh toán, tiền âm, lỗi cú pháp tiền tệ), agent lập tức trả lại `AgentResult` với `status` phù hợp (`data_error`, `conflict`, `not_found`) cùng mảng `errors` chuẩn bị theo mô tả `ErrorDetail`.

## Task List

### Phase 1: Foundation - Data Loader for Payment & Items
- [ ] Task 1: Xây dựng cơ sở truy vấn `OlistDataLoader` cho Payment và Items trong `utils/data_loader.py` kèm unit tests trong `tests/test_data_loader.py`.

### Checkpoint: Foundation
- [ ] Lệnh kiểm chứng: `python -m unittest tests/test_data_loader.py -v` hoàn tất thành công.
- [ ] Đảm bảo dữ liệu tải về giữ nguyên dạng string, không sửa đổi source CSV.

### Phase 2: Core Features - Payment Agent Standard Reconciliation
- [ ] Task 2: Triển khai lớp `PaymentAgent` trong `agents/payment_agent.py` xử lý trường hợp chuẩn: tính toán tổng tiền, đối soát tài chính (`difference_brl <= 0.10`), phát hiện chia nhỏ thanh toán (`payment_count >= 2`) và sinh ra chuẩn `AgentResult` với `facts`, `entity_candidates`, `evidence_candidates`.
- [ ] Viết unit tests kiểm chứng các testcase thanh toán chuẩn trong `tests/test_payment_agent.py`.

### Checkpoint: Core Features
- [ ] Lệnh kiểm chứng: `python -m unittest tests/test_payment_agent.py -v` hoàn tất thành công.
- [ ] Các con số tiền tệ chính xác tuyệt đối ở kiểu số thập phân, làm tròn 2 chữ số theo `ROUND_HALF_UP`.

### Phase 3: Polish & Edge Cases (Trường hợp biên & Lỗi vi phạm)
- [ ] Task 3: Bổ sung logic xử lý toàn diện các trường hợp biên của Payment Agent:
  - Order không có payment row nào -> trả `payments=[]`, totals = `0.00`, status `success` (không coi là lỗi, không tự gán/bịa payment ID).
  - `payment_sequential` trùng lặp trong cùng order -> trả `status="data_error"`.
  - Giá trị tiền không parse được hoặc âm bất thường -> trả `status="data_error"`.
  - Mâu thuẫn tổng tiền kiểm tra chéo (khi có thông số đối chiếu gây xung đột từ Coordinator) -> trả `status="conflict"`.
- [ ] Bổ sung các ca kiểm thử unit test cho edge cases vào `tests/test_payment_agent.py`.

### Checkpoint: Complete
- [ ] Toàn bộ unit tests chạy xanh (PASS): `python -m unittest discover -s tests -v`.
- [ ] Mã nguồn đáp ứng toàn bộ các Tiêu chí Thành công (Success Criteria) đặt ra tại `specs/payment_agent_spec.md`.
- [ ] Nghiệm thu với human trước khi bàn giao.

## Risks and Mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| Hiệu năng tra cứu file CSV 100k dòng lặp đi lặp lại có thể chậm | Low-Medium | Thêm bộ nhớ đệm (caching/index theo `order_id` trong bộ nhớ trong lần đọc đầu của DataLoader) mà không ghi hay chỉnh sửa file đĩa gốc. |
| Sai lệch số thập phân do ép kiểu nhầm về float | High | Viết hàm helper chuẩn cho phép tính tiền: `Decimal(str(val)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)` và test nghiêm ngặt trong Unit Test. |

## Open Questions
- Không có open question; mọi thiết kế đã ăn khớp trọn vẹn với yêu cầu của tài liệu kiến trúc.
