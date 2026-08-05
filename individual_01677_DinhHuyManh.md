# Member Role Report - Day 9: Multi-Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Đinh Huy Mạnh |
| MSSV | 2A202601677 |
| Khóa/Lớp | K3 |
| Vai trò chính | Order & Seller Agent |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Order & Seller Agent | `agents/order_seller_agent.py`, `OrderSellerAgent.run()` | `AgentTask` chứa `order_id`, `lookup_order_id` và cờ kiểm tra product | `AgentResult` chứa order facts, item/seller facts, tổng tiền và evidence | Hoàn thành |
| Tiện ích domain | `agents/domain_utils.py` | Chuỗi timestamp, tiền, sequence từ CSV | Giá trị đã parse và danh sách ID duy nhất | Hoàn thành |
| Quan hệ dữ liệu | Orders, Order Items, Sellers, Products | Join theo `order_id`, `seller_id`, `product_id` | Entity candidates có referential integrity | Hoàn thành |
| Kiểm thử tích hợp | `tests/test_agents.py` | Case thật trong `input/` và database CSV | Xác nhận tổng item/freight khớp Payment Agent | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Cung cấp `item_total_brl` và `freight_total_brl` | Tuấn - Payment Agent | Coordinator có hai nguồn độc lập để phát hiện total conflict |
| Cung cấp shipping limit và seller ID | Hưng - Delivery Agent | Có dữ liệu xác định seller bàn giao trễ |
| Cung cấp entity/evidence candidates | Quân - Policy, Khiêm - Verifier | Policy chọn đủ ID và Verifier kiểm tra tồn tại trong CSV |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Tra cứu đúng một order theo claimed ID | `OlistDataLoader.get_order()` | Phát hiện `ORDER_NOT_FOUND` hoặc trả order record thật | Test domain agent với case thật |
| Tổng hợp item độc lập | `OrderSellerAgent.run()` | `items`, `item_total_brl`, `freight_total_brl` dùng Decimal | So sánh với Payment facts trong test |
| Kiểm tra seller/product reference | `seller_exists()`, `product_exists()` | Dữ liệu thiếu trả `DATA_INTEGRITY_ERROR`, không bịa facts | Unit/integration tests |
| Tạo ID và evidence ổn định | `EntityCandidates`, `success_result()` | `order:<id>`, `item:<order>:<seq>`, `seller:<id>` | Verifier và output audit |
| Xử lý order không có item | Nhánh `raw_items=[]` | Item/seller rỗng, item/freight bằng `0.0` | Case `EC_005` trong test |

Artifact chính của phần việc là `AgentResult` Order & Seller. Kết quả này vừa cung cấp dữ liệu tài chính cho Coordinator đối chiếu, vừa cung cấp item/seller candidates để Policy tạo `affected_entities` đầy đủ.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Một order có thể có nhiều item và seller. Agent phải tính tổng mà không tạo tích Descartes với bảng payment, bảo toàn ID dạng chuỗi, kiểm tra foreign key cần thiết và xác định seller nào bàn giao hàng cho carrier sau `shipping_limit_date`.

### Cách triển khai

Agent xác nhận `payload.lookup_order_id == task.order_id`, sau đó lấy order và toàn bộ item theo `order_id`. Item được parse `order_item_id`, sắp xếp theo sequence và chặn sequence trùng. Mỗi dòng dùng `Decimal` để cộng `price` và `freight_value`.

`handoff_after_limit` được tính khi cả `order_delivered_carrier_date` và `shipping_limit_date` tồn tại. Seller ID phải tồn tại trong bảng sellers; product ID cũng được kiểm tra khi Coordinator bật `include_product_validation`. Các ID được tạo theo format contract, loại trùng nhưng giữ thứ tự.

Nếu order tồn tại nhưng không có item row, đây không phải lỗi dữ liệu: agent trả `items=[]`, `item_ids=[]`, `seller_ids=[]`, hai tổng tiền bằng 0.0 và vẫn giữ evidence của order.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `AgentTask`; payload có `lookup_order_id`, `include_product_validation` |
| Output | `AgentResult` tên `order_seller`, status, facts, entity/evidence candidates |
| CSV phụ thuộc | `olist_orders_dataset.csv`, `olist_order_items_dataset.csv`, `olist_sellers_dataset.csv`, tùy chọn products |
| Module sử dụng output | Coordinator, Delivery/Payment cross-check, Policy và Verifier |
| Điều kiện lỗi | Payload mismatch, order không tồn tại, sequence trùng, tiền/timestamp lỗi, seller/product reference thiếu |

### Cách xác minh

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agents.py
.\.venv\Scripts\ruff.exe check agents\order_seller_agent.py agents\domain_utils.py
```

- Kết quả mong đợi: agent trả success cho dữ liệu hợp lệ và totals khớp Payment Agent.
- Kết quả thực tế gần nhất của toàn suite: `21 passed`.
- Artifact/log: event `agent_completed` có `agent=order_seller` trong `logging/trace.jsonl`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Orders, items và payments đều có quan hệ 1:N. Join tất cả trước khi cộng tiền có thể nhân bản dòng.
- **Các phương án đã cân nhắc:** Join một dataframe lớn; hoặc query từng bảng riêng theo order rồi aggregate độc lập.
- **Phương án đã chọn:** Order & Seller Agent chỉ aggregate bảng item; Payment Agent aggregate payment riêng; Coordinator mới so sánh totals.
- **Lý do:** Tránh tích Descartes, giữ ownership giữa agent và cho phép phát hiện conflict giữa hai nguồn tính độc lập.
- **Bằng chứng:** Test xác nhận `item_total_brl` và `freight_total_brl` của Order & Seller bằng hai trường check của Payment.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng:** Order trạng thái unavailable/canceled có thể tồn tại trong orders và payments nhưng không có item row.
- **Tái hiện:** Chạy case `EC_005`; data loader trả order và payment nhưng `get_items()` trả danh sách rỗng.
- **Nguyên nhân gốc:** Thiếu item là trạng thái dữ liệu hợp lệ cho một số order, không phải luôn là foreign-key corruption.
- **Cách xử lý:** Khởi tạo totals bằng `Decimal("0")`, giữ danh sách item/seller rỗng và trả success thay vì `DATA_INTEGRITY_ERROR`.
- **Xác minh:** Output case không item có `item_ids=[]`, `seller_ids=[]`, `item_total_brl=0.0`, `freight_total_brl=0.0`.
- **Điều học được:** Phải phân biệt “không có bản ghi hợp lệ” với “bản ghi có tham chiếu hỏng”.

## 7. Hiểu biết về luồng end-to-end

1. Coordinator validate case rồi gọi Order & Seller, Payment và Delivery song song.
2. Order & Seller trả order/item/seller facts; Payment trả đối soát; Delivery trả attribution.
3. Coordinator kiểm tra identity và totals trước khi tạo EvidenceBundle có digest.
4. Policy Python áp dụng rule, Qwen tạo structured result và confidence; các trường khách quan bị khóa.
5. Verifier đọc lại CSV, kiểm tra đủ ID, evidence, tài chính và policy. PASS mới ghi output.
6. Nếu Order & Seller lỗi retryable, Coordinator retry có giới hạn; không ghi partial output khi case fail.

## 8. Cam kết của thành viên

- [x] Nội dung phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ Order & Seller Agent.
- [x] Tôi chỉ ghi kết quả đã được kiểm chứng trong repo hiện tại.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo không sao chép nguyên văn báo cáo của thành viên khác.

**Họ và tên:** Đinh Huy Mạnh

**Ngày xác nhận:** 2026-08-05
