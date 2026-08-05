# Member Role Report — Day 9: Multi Agent A2A

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
| Verifier Agent | `agents/verifier_agent.py`, `VerifierAgent.run()` | Case input, EvidenceBundle, PolicyDecision, domain results và draft output | `AgentResult` chứa verdict PASS/FAIL, checks, recomputed values và structured errors | Hoàn thành |
| Kiểm tra identity và lineage | `_digest()`, `identity_ok` | Case/order/run/correlation ID, bundle version/digest và draft digest | Phát hiện stale draft hoặc handoff sai identity | Hoàn thành |
| Đối soát entity, evidence và tài chính | `expected_entities`, `valid_evidence`, `financial_ok` | Candidate IDs và dữ liệu order/items/payments/sellers | Kết quả đối chiếu độc lập từ CSV | Hoàn thành |
| Kiểm tra policy và output limits | `policy_ok`, `limits_ok` | Policy decision và FinalOutput | Phát hiện sai rule, refund, action hoặc vượt giới hạn | Hoàn thành |
| Kiểm thử Verifier | Phần Verifier trong `tests/test_agents.py` | Các case đại diện cho sáu nhánh policy | Xác minh handoff Verifier trả PASS | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Thống nhất contract handoff | Coordinator Agent | Chuẩn hóa case ID, order ID, run ID, correlation ID, draft version và digest |
| Đối chiếu cách tính tổng tiền | Payment Agent | Thống nhất cộng item, freight và payment bằng `Decimal`, không nhân payment theo installments |
| Kiểm tra entity candidates | Order/Seller Agent | Bảo đảm item, seller và order ID đều truy vết được về dữ liệu CSV |
| Kiểm tra quyết định cuối | Policy Agent | Đối chiếu rule, issue, cause, party, refund, action và evidence trước khi ghi output |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Validate toàn bộ payload | `agents/verifier_agent.py` | Payload sai trả `SCHEMA_VIOLATION` thay vì làm hỏng pipeline | Chạy test với payload thiếu field |
| Kiểm tra identity và digest | `identity_ok`, `_digest()` | Chặn draft cũ hoặc draft thuộc nhầm case | Sửa `draft_digest` và kiểm tra verdict FAIL |
| Tính lại số tiền từ CSV | `VerifierAgent.run()` | Tính lại item, freight và payment totals độc lập | So sánh `recomputed_values` với output |
| Kiểm tra đầy đủ entity ID | `expected_entities` | Không cho danh sách rỗng hoặc thiếu ID vượt qua | Test bỏ một order/item/seller ID |
| Chạy lại policy xác định | `self._policy.run(policy_task)` | Đối chiếu decision và draft với `EC_POLICY_V1` | Test sáu policy branch |
| Định tuyến lỗi | `_error()` | Trả đúng `retry_target` cho Coordinator, Payment, Policy hoặc Order/Seller | Kiểm tra trường `errors` trong AgentResult |

Artifact chính là `VerificationResult` nằm trong `AgentResult.facts`. Artifact gồm verdict, bảy checks (`schema`, `identity`, `entities`, `evidence`, `financials`, `policy`, `limits`), các giá trị tính lại và danh sách lỗi có cấu trúc. Chỉ draft có PASS đúng version/digest mới được Coordinator ghi vào output.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Trong hệ thống nhiều agent, một draft có thể đúng schema nhưng vẫn sai dữ liệu, sai tổng tiền, sai policy hoặc nhận nhầm kết quả từ case khác. Nếu Verifier chỉ tin lại kết quả của các agent trước thì lỗi có thể đi xuyên pipeline. Phần việc của tôi tạo một cổng kiểm tra độc lập trước bước ghi file.

### Cách triển khai

Verifier thực hiện tuần tự bảy nhóm kiểm tra. Đầu tiên, payload được parse bằng các Pydantic model để bảo đảm đúng contract. Sau đó agent kiểm tra identity xuyên suốt case, evidence bundle, policy decision, domain results và draft. Digest của draft được tính lại bằng SHA-256 trên JSON canonical để phát hiện draft bị thay đổi sau khi verify.

Tiếp theo, Verifier đọc lại order, items và payments từ `OlistDataLoader`. Các tổng item, freight và payment được tính bằng `Decimal` rồi làm tròn theo helper tiền tệ. Entity trong draft phải bằng chính xác candidate list đã giới hạn, đồng thời từng item/payment/seller ID phải tồn tại và thuộc order đang xử lý. Evidence ID chỉ được lấy từ order, item, payment, seller hoặc policy cause hợp lệ.

Cuối cùng, Verifier chạy lại deterministic `PolicyAgent` trên cùng EvidenceBundle. Các trường rule priority, primary issue, case status, ranked causes, responsible parties, selected entities, refund, resolution actions và evidence IDs được đối chiếu với policy decision và FinalOutput. Agent chỉ trả PASS khi cả bảy checks đều đúng.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `AgentTask.payload` chứa `case_input`, `evidence_bundle`, `policy_decision`, `draft_output`, `agent_results`, `draft_version`, `draft_digest` |
| Output | `AgentResult.facts` chứa verdict, checks, recomputed values, errors và warnings |
| Module phụ thuộc | `agents/coordinator.py`, `agents/policy_agent.py`, `agents/domain_utils.py`, `utils/data_loader.py` |
| Module sử dụng output | Coordinator dùng verdict để retry đúng agent hoặc ghi output |
| Điều kiện lỗi cần xử lý | Sai schema/identity, ID giả hoặc thiếu, evidence không tồn tại, sai tổng tiền, sai policy, stale digest và vượt output limits |

### Cách xác minh

```powershell
python -m pytest tests/test_agents.py -q
python -m py_compile agents/verifier_agent.py
```

- **Kết quả mong đợi:** Các case hợp lệ trả PASS; draft sai digest, entity, evidence, policy hoặc số tiền trả FAIL.
- **Kết quả thực tế:** Sáu case đại diện `EC_001`, `EC_002`, `EC_003`, `EC_004`, `EC_005`, `EC_009` đi qua handoff Verifier; các tình huống cố ý sửa draft đều bị chặn.
- **Artifact/log:** `AgentResult.facts` của Verifier và sự kiện `verification_completed` trong `trace.jsonl`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Cần quyết định cách kiểm tra affected entities trong draft có đầy đủ và hợp lệ hay không.
- **Các phương án đã cân nhắc:** (1) Chỉ kiểm tra các ID đã chọn là tập con của candidate IDs; (2) yêu cầu draft bằng chính xác candidate list đã giới hạn rồi kiểm tra từng ID với CSV.
- **Phương án đã chọn:** Dùng equality với `bundle.entity_candidates[:5]`, sau đó kiểm tra referential integrity cho từng order/item/payment/seller ID.
- **Lý do:** Phép subset ngăn ID giả nhưng không phát hiện danh sách rỗng hoặc thiếu ID. Equality bảo đảm completeness, còn đối chiếu CSV bảo đảm validity.
- **Bằng chứng quyết định phù hợp:** Khi cố ý xóa một entity khỏi draft, Verifier trả `INVALID_ENTITY_SELECTION`; happy path vẫn PASS với đủ entity dự kiến.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Output có `order_ids=[]` hoặc thiếu seller nhưng check entity vẫn có thể PASS.
- **Lệnh hoặc bước tái hiện:** Tạo draft từ một case hợp lệ, xóa `order_ids` rồi gọi `VerifierAgent.run()`.
- **Nguyên nhân gốc:** Điều kiện cũ dùng `set(selected).issubset(expected)`. Tập rỗng luôn là tập con hợp lệ nên chỉ kiểm tra được validity, chưa kiểm tra completeness.
- **Cách xử lý:** Tạo `expected_entities` từ EvidenceBundle, so sánh equality với toàn bộ `AffectedEntities`, sau đó tiếp tục xác minh từng ID bằng dữ liệu CSV.
- **Cách xác minh sau khi sửa:** Chạy lại test với draft thiếu ID nhận verdict FAIL và lỗi `INVALID_ENTITY_SELECTION`; draft đầy đủ nhận PASS.
- **Điều học được:** Với output contract, “không chứa dữ liệu sai” và “chứa đủ dữ liệu cần thiết” là hai invariant khác nhau và phải được kiểm tra riêng.

## 7. Hiểu biết về luồng end-to-end

1. Chương trình đọc từng JSON trong thư mục input và validate case trước khi khởi chạy pipeline.
2. Coordinator tạo task có chung run ID/correlation ID rồi giao cho Order/Seller, Payment và Delivery Agent thu thập facts độc lập.
3. Coordinator tổng hợp facts và candidates thành EvidenceBundle, đồng thời kiểm tra conflict giữa các domain results.
4. Policy Agent áp dụng `EC_POLICY_V1` để chọn primary issue, case status, cause, responsible party, affected entities, refund, actions và evidence.
5. Coordinator dựng FinalOutput, gắn draft version và tạo SHA-256 digest cho nội dung draft.
6. Verifier parse lại contract, đối chiếu identity, đọc lại CSV, tính lại totals và chạy lại policy để kiểm tra draft.
7. Nếu FAIL, lỗi có `retry_target` để Coordinator gọi lại đúng owner và tạo draft version mới. Nếu PASS, đúng draft/version/digest mới được ghi atomic vào output.
8. Batch runner lặp luồng này cho 50 case, tạo output tương ứng và lưu trace để chứng minh delegation/handoff giữa các agent.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ Verifier Agent.
- [x] Tôi hiểu contract giữa Verifier, Coordinator và các domain agents.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không sao chép nguyên văn báo cáo của thành viên khác.

**Họ và tên:** Lê Minh Khiêm  
**Ngày xác nhận:** 2026-08-05
