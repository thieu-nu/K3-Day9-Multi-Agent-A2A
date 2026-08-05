# Member Role Report - Day 9: Multi-Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Lê Minh Khiêm |
| MSSV | 2A202601645 |
| Khóa/Lớp | K3 |
| Vai trò chính | Verifier Agent |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Verifier Agent | `agents/verifier_agent.py`, `VerifierAgent.run()` | Case, domain results, bundle, policy decision và draft | `VerificationResult` PASS/FAIL cùng checks và structured errors | Hoàn thành |
| Kiểm tra độc lập CSV | Các phép đọc lại order/items/payments/sellers | `order_id` của task | Totals và entity sets tính lại độc lập | Hoàn thành |
| Schema và lineage gate | `FinalOutput`, version/digest checks | Draft cùng `draft_version`, `draft_digest` | Chặn stale hoặc sai identity | Hoàn thành |
| Output limits | Check `limits` | Entity, evidence, cause, party, action, confidence | PASS chỉ khi đúng giới hạn README | Hoàn thành |
| Retry routing | `AgentError.retry_target` | Nhóm lỗi phát hiện | Trả đúng owner agent cho Coordinator | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Đối chiếu totals độc lập | Mạnh và Tuấn | Phát hiện lệch item/freight/payment trước khi ghi output |
| Kiểm tra attribution và cause | Hưng | Delivery facts không thể tạo evidence/seller giả |
| Kiểm tra policy và selected IDs | Quân | Rule, refund, action, entity và evidence phải khớp baseline Python |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Validate toàn bộ verifier payload | Pydantic models trong `agents/coordinator.py` | Schema sai trả `SCHEMA_VIOLATION` | Tests coordinator/verifier |
| Kiểm tra identity và digest | `identity_ok`, `_digest()` | Chặn case/order/run/correlation hoặc draft digest sai | Test stale verifier |
| Tính lại số tiền từ CSV | `VerifierAgent.run()` | Recomputed item, freight, payment totals | So sánh output với database |
| Kiểm tra đầy đủ entity ID | `expected_entities` | Dùng equality, không cho tập rỗng vượt qua | Test bỏ selected ID |
| Chạy lại Policy Python | `self._policy.run(policy_task)` | Đối chiếu issue, cause, party, refund, action, entity/evidence | Test đủ sáu policy branch |
| Chỉ PASS khi đủ bảy checks | `CHECK_NAMES` | `schema`, `identity`, `entities`, `evidence`, `financials`, `policy`, `limits` | `VerificationResult` validator |

Artifact chính là `VerificationResult`. PASS gắn với đúng `draft_version` và SHA-256 `draft_digest`; một draft thay đổi bắt buộc verify lại, vì vậy PASS cũ không thể được dùng để ghi output mới.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Nếu Verifier chỉ kiểm tra schema hoặc tin lại facts từ các agent trước, một lỗi chung có thể đi xuyên pipeline. Verifier phải có nguồn kiểm tra độc lập, phân biệt lỗi thuộc domain, policy hay coordinator và ngăn mọi draft chưa đủ bằng chứng được ghi ra.

### Cách triển khai

Verifier parse toàn bộ payload thành các Pydantic model nghiêm ngặt. Sau đó kiểm tra identity của case, bundle, decision, draft và domain result. Draft digest được tính lại từ JSON canonical.

Agent đọc lại Orders, Items và Payments từ `OlistDataLoader`, dùng Decimal để tính totals. Entity output phải bằng chính xác các candidates kỳ vọng sau giới hạn 5, đồng thời từng ID phải tồn tại trong CSV. Evidence phải thuộc tập ID có thể dựng từ order/item/payment/seller và cause của policy.

Verifier gọi lại deterministic `PolicyAgent` trên EvidenceBundle để tạo expected decision. Các trường rule, selected entity/evidence, refund và action được so sánh; confidence được chấp nhận từ Policy Qwen nhưng phải nằm trong `[0,1]` và draft phải giữ đúng giá trị đó.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `AgentTask.payload`: case, ba domain results, EvidenceBundle, PolicyDecision, FinalOutput, version/digest |
| Output | `AgentResult` verifier chứa `VerificationResult` PASS/FAIL, checks, recomputed values, errors |
| Module phụ thuộc | Data loader, PolicyAgent, Pydantic contract và helper tiền/sequence |
| Module sử dụng output | Coordinator routing; OutputStore chỉ chạy sau PASS |
| Điều kiện lỗi | Schema, identity, entity/evidence giả hoặc thiếu, totals, policy, limits, stale digest |

### Cách xác minh

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agents.py tests\test_coordinator.py
.\.venv\Scripts\mypy.exe agents\verifier_agent.py agents\coordinator.py
```

- Kết quả mong đợi: happy path PASS; stale digest, policy mismatch và thiếu ID bị chặn.
- Kết quả thực tế gần nhất của toàn suite: `21 passed`.
- Artifact/log: `verification_completed` trong trace có verdict, error details và draft reference.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Có thể kiểm tra entity theo subset để cho phép Policy chọn ít ID hơn candidates, nhưng tập rỗng cũng là subset hợp lệ.
- **Các phương án đã cân nhắc:** Chỉ kiểm tra ID không giả bằng subset; hoặc yêu cầu output bằng expected selection đã giới hạn.
- **Phương án đã chọn:** Equality với `bundle.entity_candidates[:5]`, sau đó vẫn kiểm tra referential integrity từng ID.
- **Lý do:** Grader đánh giá affected entities; tính đúng phải bao gồm cả không bịa và không bỏ ID cần thiết.
- **Bằng chứng:** Audit cũ phát hiện 44/50 output thiếu order ID dù Verifier PASS; sau thay đổi, test cố tình bỏ ID trả FAIL/conflict.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng:** Output có `order_ids=[]` hoặc thiếu seller nhưng event `verification_completed` vẫn PASS.
- **Tái hiện:** Với expected order set `{order_id}`, phép `set([]).issubset({order_id})` trả true.
- **Nguyên nhân gốc:** Verifier chỉ chứng minh selected IDs hợp lệ, không chứng minh output đã chọn đủ IDs.
- **Cách xử lý:** Tạo `expected_entities` từ EvidenceBundle, so sánh equality với draft và thêm selected entity/evidence vào policy comparison.
- **Xác minh:** Test Policy bỏ `order_ids` và domain API bỏ candidates đều bị chặn; 50 case deterministic vẫn PASS.
- **Điều học được:** Với output contract, completeness và validity là hai invariant khác nhau, cần kiểm tra cả hai.

## 7. Hiểu biết về luồng end-to-end

1. Input được validate trước khi bất kỳ domain agent nào chạy.
2. Ba domain agent trả facts và candidates độc lập; Coordinator phát hiện conflict rồi tạo bundle.
3. Policy Python quyết rule; Qwen trả structured decision/confidence nhưng không được đổi trường khóa.
4. Coordinator tạo FinalOutput và digest, sau đó mới gọi Verifier.
5. Verifier tái tính từ CSV và policy; lỗi có `retry_target` để Coordinator gọi lại owner phù hợp.
6. Chỉ PASS đúng draft hiện tại mới ghi atomic. Case fail không ghi output mới và không xóa artifact cũ.

## 8. Cam kết của thành viên

- [x] Nội dung phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ Verifier Agent.
- [x] Tôi chỉ ghi kết quả đã được kiểm chứng trong repo hiện tại.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo không sao chép nguyên văn báo cáo của thành viên khác.

**Họ và tên:** Lê Minh Khiêm

**Ngày xác nhận:** 2026-08-05
