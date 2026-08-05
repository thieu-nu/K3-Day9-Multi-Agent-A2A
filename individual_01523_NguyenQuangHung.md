# Member Role Report - Day 9: Multi-Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Nguyễn Quang Hưng |
| MSSV | 2A202601523 |
| Khóa/Lớp | K3 |
| Vai trò chính | Delivery Agent |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Delivery Agent | `agents/delivery_agent.py`, `DeliveryAgent.run()` | `AgentTask` có `lookup_order_id` | Delivery facts, handoff facts, attribution và root-cause candidates | Hoàn thành |
| So sánh timestamp | `parse_timestamp()` trong `agents/domain_utils.py` | Các mốc carrier, delivered, estimated, shipping limit | Boolean giao trễ/đúng hạn và bàn giao trễ | Hoàn thành |
| Entity/evidence delivery | `EntityCandidates`, `success_result()` | Order item và seller của order | Order/item/seller IDs cùng evidence đúng format | Hoàn thành |
| Kiểm thử tích hợp | `tests/test_agents.py` | Case thật đại diện các nhánh policy | Xác nhận seller/logistics/within-estimate attribution | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Đối chiếu seller handoff | Mạnh - Order & Seller Agent | Hai agent dùng cùng quy ước `carrier_date > shipping_limit_date` |
| Cung cấp attribution | Quân - Policy Agent | Phân biệt late seller, late logistics và claim không được hỗ trợ |
| Cung cấp dữ kiện độc lập | Khiêm - Verifier Agent | Verifier có thể kiểm tra lại timestamp và seller candidates từ CSV |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| So sánh giao thực tế với estimated date | `DeliveryAgent.run()` | `delivered_after_estimate`, `delivery_within_estimate` | Case `EC_001`, `EC_002`, `EC_009` |
| So sánh carrier handoff theo từng item | `seller_handoffs` | Mỗi item có shipping limit, carrier date và boolean kết quả | Inspect AgentResult/trace |
| Phân loại bên có khả năng chịu trách nhiệm | `attribution_candidate` | `seller`, `logistics_provider`, `none`, `not_applicable` hoặc `unknown` | Test đủ sáu policy branch |
| Tạo root-cause candidates | `root_cause_candidates` | Cause code khớp bảng README | Policy và Verifier kiểm tra |
| Xử lý timestamp thiếu | Warnings và nhánh `unknown` | Không suy diễn giao trễ khi thiếu mốc quan trọng | Test schema và data validation |

Artifact chính là Delivery `AgentResult`. Ví dụ khi giao sau estimated và có ít nhất một item được carrier nhận sau shipping limit, agent trả `attribution_candidate="seller"`, danh sách seller vi phạm và cause `SELLER_HANDOFF_AFTER_LIMIT`.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Chỉ biết đơn giao trễ chưa đủ để xác định trách nhiệm. Cần so sánh hai lớp thời gian: ngày giao cho khách với estimated date, và ngày carrier nhận hàng với shipping limit của từng item. Một order nhiều item có thể có nhiều shipping limit nhưng bộ case chính thức không có tình huống trách nhiệm seller mơ hồ.

### Cách triển khai

Agent validate lookup identity, lấy order và item rows. Timestamp được parse về kiểu datetime trước khi so sánh. `delivered_after_estimate` chỉ true khi cả hai mốc tồn tại và delivered date lớn hơn estimated date. Với từng item, `handoff_after_limit` chỉ được tính khi carrier date và shipping limit đều có.

Thứ tự attribution:

1. Order canceled/unavailable: `not_applicable`.
2. Thiếu delivery hoặc estimate: `unknown` và warning.
3. Giao trong hạn: `none`, cause `DELIVERY_WITHIN_ESTIMATE`.
4. Giao trễ và có seller handoff trễ: `seller`.
5. Giao trễ, có handoff và tất cả handoff đúng hạn: `logistics_provider`.
6. Còn lại: `unknown` do dữ kiện handoff chưa đủ.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `AgentTask`; payload `lookup_order_id` phải bằng envelope `order_id` |
| Output | `AgentResult` có delivery facts, candidates, evidence, warnings hoặc structured errors |
| CSV phụ thuộc | Orders và Order Items |
| Module sử dụng output | EvidenceBundle, Policy Agent và Verifier Agent |
| Điều kiện lỗi | Order không tồn tại, payload mismatch, timestamp/sequence lỗi hoặc item sequence trùng |

### Cách xác minh

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agents.py
.\.venv\Scripts\ruff.exe check agents\delivery_agent.py agents\domain_utils.py
```

- Kết quả mong đợi: các nhánh seller, logistics và within-estimate sinh đúng issue ở output.
- Kết quả thực tế gần nhất của toàn suite: `21 passed`.
- Artifact/log: event `agent_completed` có `agent=delivery`; EvidenceBundle chứa `delivery_facts`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Khi timestamp thiếu, gán mặc định false có thể khiến Policy kết luận logistics hoặc giao đúng hạn sai.
- **Các phương án đã cân nhắc:** Điền timestamp suy đoán; coi mọi thiếu dữ liệu là lỗi terminal; hoặc dùng trạng thái `unknown` và warning.
- **Phương án đã chọn:** Không suy diễn timestamp, trả `unknown` khi thiếu dữ kiện cần thiết; canceled/unavailable dùng `not_applicable` vì delivery không còn là rule ưu tiên.
- **Lý do:** Tách rõ thiếu dữ liệu kỹ thuật với trạng thái nghiệp vụ không áp dụng, tránh false attribution.
- **Bằng chứng:** Policy chỉ match late seller/logistics khi `delivered_after_estimate` và attribution tương ứng cùng đúng.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng:** Một số order canceled/unavailable không có delivery timestamp; nếu xử lý như order giao hàng thông thường sẽ sinh warning hoặc cause không liên quan.
- **Tái hiện:** Chạy case unavailable có payment nhưng không có item/delivery hoàn chỉnh.
- **Nguyên nhân gốc:** Logic attribution ban đầu không tách trạng thái order trước khi đánh giá chất lượng timestamp.
- **Cách xử lý:** Ưu tiên kiểm tra `order_status in {"canceled", "unavailable"}` và trả `not_applicable`, cause rỗng.
- **Xác minh:** Policy vẫn match rule priority 1/2 dựa trên order status và payment; không bị delivery rule priority thấp hơn can thiệp.
- **Điều học được:** Domain agent nên biểu diễn “không áp dụng” trong facts của một kết quả thành công thay vì biến nó thành lỗi agent.

## 7. Hiểu biết về luồng end-to-end

1. Coordinator dispatch ba domain agent song song sau khi input hợp lệ.
2. Delivery chỉ chịu trách nhiệm timestamp và attribution; không tự quyết refund.
3. Coordinator gộp Delivery facts với Order/Seller và Payment facts thành EvidenceBundle.
4. Policy áp dụng thứ tự ưu tiên nên canceled/unavailable luôn đứng trước delivery rules.
5. Verifier đọc lại CSV, kiểm tra draft và policy; chỉ PASS mới ghi output.
6. Nếu Verifier chỉ ra delivery mismatch và lỗi retryable, Coordinator có thể gọi lại đúng owner agent trong giới hạn retry.

## 8. Cam kết của thành viên

- [x] Nội dung phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ Delivery Agent.
- [x] Tôi chỉ ghi kết quả đã được kiểm chứng trong repo hiện tại.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo không sao chép nguyên văn báo cáo của thành viên khác.

**Họ và tên:** Nguyễn Quang Hưng

**Ngày xác nhận:** 2026-08-05
