# Member Role Report - Day 9: Multi-Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Trần Hoàng Quân |
| MSSV | 2A202601805 |
| Khóa/Lớp | K3 |
| Vai trò chính | Policy Agent, điều phối Coordinator, tích hợp agent và utilities dùng chung |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Policy Agent | `agents/policy_agent.py`, `PolicyAgent.run()` | `EvidenceBundle`, `EC_POLICY_V1` | `PolicyDecision` có issue, cause, party, refund, action và evidence | Hoàn thành |
| Coordinator | `agents/coordinator.py`, `CoordinatorAgent` | Một case JSON và năm `AgentRunner` | Workflow LangGraph, draft đã verify và output JSON | Hoàn thành |
| Tích hợp Qwen | `agents/api_runner.py` | Kết quả Python tool và JSON Schema | `AgentResult` do `Qwen/Qwen3.5-9B` sinh, có kiểm tra trường khóa | Hoàn thành |
| Utilities dữ liệu | `utils/data_loader.py`, `OlistDataLoader` | Các bảng CSV trong `data/` | Index chỉ đọc theo order, seller và product cho toàn bộ agent | Hoàn thành |
| Utilities LLM | `utils/llm_client.py`, `TogetherStructuredClient` | Prompt, response model và `TOGETHER_API_KEY` từ môi trường | Structured JSON đã validate, có retry parse và timeout | Hoàn thành |
| Utilities domain | `agents/domain_utils.py` | Giá trị tiền, timestamp, sequence và danh sách ID | Decimal/timestamp/sequence chuẩn hóa và unique ổn định | Hoàn thành |
| Batch runner và audit | `main.py`, `logging/trace.jsonl`, `logging/metadata.json` | 50 input hoặc một `--case` | Output atomic, trace lineage và metadata lượt chạy | Hoàn thành |
| Tài liệu vận hành | `architecture.md`, `howtorun.md` | Source và yêu cầu README | Sơ đồ handoff, contract và lệnh chạy | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Chuẩn hóa `AgentTask`, `AgentResult` và error contract | Mạnh, Tuấn, Hưng, Khiêm | Các agent trao đổi cùng contract version, identity và retry target |
| Kiểm tra đầy đủ entity ID | Policy và Verifier | Không còn cho phép tập ID rỗng vượt qua bằng phép kiểm tra subset |
| Bổ sung trace lineage | Toàn pipeline | Event có source, task ID, bundle digest, policy task và draft digest |
| Cung cấp data/LLM utilities thống nhất | Mạnh, Tuấn, Hưng, Khiêm | Các agent không tự đọc CSV hoặc tự gọi provider theo những contract khác nhau |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Cài đặt bảng sáu rule theo đúng thứ tự ưu tiên | `agents/policy_agent.py` | Phân loại đủ sáu `primary_issue` trong README | `pytest tests/test_agents.py` |
| Fan-out ba domain agent và gom EvidenceBundle | `CoordinatorAgent._build_graph()`, `_build_evidence_bundle()` | Ba domain chạy song song, bundle có version và SHA-256 digest | `pytest tests/test_coordinator.py` |
| Khóa quyết định Python trước Policy Qwen | `ApiGeneratedAgent._policy_mismatches()` | Qwen không được đổi rule, refund, action, ID hoặc bundle identity | Test `POLICY_API_MISMATCH` |
| Để Qwen tự đánh giá confidence | `agents/api_runner.py` | Loại confidence mặc định khỏi API context; Qwen trả confidence và basis | Test policy API trả confidence `0.73` |
| Chỉ ghi file sau Verifier PASS | `_verify_node()`, `_write_node()` | Không có partial output; ghi atomic đúng tên `EC_NNN.json` | Test happy path và stale verifier |
| Xây dựng data access dùng chung | `utils/data_loader.py` | Polars đọc cột cần thiết dưới dạng string, index in-memory và kiểm tra primary key | Domain integration tests |
| Đóng gói Together structured output | `utils/llm_client.py` | Model cố định 9B, JSON Schema, parse retry và lỗi cấu hình rõ ràng | Test thiếu API key và API wrapper tests |
| Chuẩn hóa dữ liệu domain | `agents/domain_utils.py` | Tiền BRL làm tròn 2 chữ số, timestamp ISO, sequence dương, unique giữ thứ tự | Toàn bộ agent tests |

Artifact cụ thể là output cuối có đầy đủ `assessment`, entity, root cause, evidence, tài chính và action. Coordinator chỉ tạo artifact sau khi `VerificationResult.verdict == "PASS"` khớp đúng `draft_version` và `draft_digest`.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Ba domain agent trả về các góc nhìn khác nhau. Hệ thống cần áp dụng policy nhất quán, không để LLM tự đổi số tiền hoặc ID, nhưng vẫn phải gọi model thật cho từng agent. Ngoài ra, mọi handoff phải chống kết quả cũ và chỉ một thành phần được quyền ghi output.

### Cách triển khai

Coordinator dùng LangGraph với chuỗi trạng thái `RECEIVED -> VALIDATED -> DISPATCHED -> COLLECTED -> POLICY_DECIDED -> DRAFTED -> VERIFYING -> VERIFIED -> WRITTEN`. Sau validate, ba node Order & Seller, Payment và Delivery được fan-out. Coordinator chỉ tạo EvidenceBundle khi đủ ba kết quả thành công và tổng item/freight giữa hai nguồn không xung đột.

`PolicyAgent` chạy Python trước, duyệt sáu rule theo priority. Kết quả này là baseline khóa các trường khách quan. Trong chế độ API, baseline được đưa cho Qwen nhưng bỏ `confidence` và `confidence_basis`; Qwen phải tự đánh giá hai trường này. API response sửa rule, refund, action, selected IDs hoặc digest sẽ trả `POLICY_API_MISMATCH` và retry có giới hạn.

Draft được tạo từ bundle và policy decision. Verifier đọc lại CSV độc lập. Chỉ PASS cho đúng version/digest hiện tại mới đi tới `AtomicJsonOutputStore`.

### Utilities dùng chung

`OlistDataLoader` dùng Polars để chỉ đọc đúng các cột cần thiết và ép toàn bộ cột định danh về string. Orders, items và payments được index riêng theo `order_id`; seller/product được giữ thành key set để kiểm tra tham chiếu. Loader trả bản sao row, vì vậy agent không sửa được index dùng chung hoặc dữ liệu gốc.

`TogetherStructuredClient` là adapter duy nhất tới provider. Model `Qwen/Qwen3.5-9B`, JSON Schema, `temperature=0`, timeout, SDK retry và structured parse retry được tập trung tại đây. API key chỉ đọc từ biến môi trường; model name và parameter size nằm trong source để metadata có thể audit.

`agents/domain_utils.py` tập trung các invariant nhỏ nhưng ảnh hưởng toàn hệ thống: tiền phải hữu hạn và không âm, làm tròn BRL bằng `ROUND_HALF_UP`; sequence phải là số nguyên dương; timestamp phải theo ISO; hàm `unique()` loại trùng nhưng giữ thứ tự đầu tiên.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `CaseInput`, ba `AgentResult` domain và `EvidenceBundle` |
| Output | `PolicyDecision`, `FinalOutput`, `CoordinatorResult` và trace JSONL |
| Module phụ thuộc | LangGraph, Pydantic, Polars và Together SDK |
| Module sử dụng output | Năm logical agent, Coordinator, Verifier, output writer và batch metadata |
| Điều kiện lỗi | CSV/file/key không hợp lệ, tiền/timestamp/sequence lỗi, thiếu API key, invalid JSON, stale digest, domain conflict, API mismatch, verifier FAIL hoặc timeout |

### Cách xác minh

```powershell
.\.venv\Scripts\ruff.exe check tests main.py agents utils
.\.venv\Scripts\mypy.exe tests main.py agents utils
.\.venv\Scripts\python.exe -m pytest
```

- Kết quả mong đợi: lint và type check không lỗi; toàn bộ test PASS.
- Kết quả thực tế gần nhất: Ruff PASS, Mypy PASS, `21 passed`.
- Artifact/log: `logging/trace.jsonl`, `logging/metadata.json`; không chứa API key.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Nếu giao toàn bộ policy cho LLM, model có thể thay đổi refund, bỏ ID hoặc trả digest cũ. Nếu chỉ dùng Python thì không đáp ứng yêu cầu agent API thực tế.
- **Các phương án đã cân nhắc:** LLM tự quyết toàn bộ; Python quyết toàn bộ; hoặc Python khóa fact khách quan rồi Qwen sinh structured decision cho phần được phép.
- **Phương án đã chọn:** Python áp dụng `EC_POLICY_V1` trước, Qwen chạy sau và tự đánh giá confidence; Pydantic cùng mismatch gate kiểm tra response.
- **Lý do:** Giữ correctness và reproducibility cho tiền/ID, đồng thời vẫn có API call và kết quả thật từ model.
- **Bằng chứng:** Test xác nhận Python chạy trước API, Qwen không thể đổi action hoặc bỏ selected ID, nhưng confidence API vẫn được giữ.

### Quyết định về utilities

- **Bối cảnh:** Mỗi agent tự đọc CSV, parse tiền và gọi API sẽ tạo logic trùng lặp và kết quả không nhất quán.
- **Các phương án đã cân nhắc:** Để từng agent tự triển khai; hoặc tập trung data access, domain parsing và provider adapter thành utilities dùng chung.
- **Phương án đã chọn:** Một `OlistDataLoader` read-only, một bộ domain parsers và một structured LLM client được inject vào agent.
- **Lý do:** Giảm I/O, ngăn join 1:N sai, giữ ID dạng string, thống nhất Decimal/timestamp và cô lập secret/provider khỏi nghiệp vụ agent.
- **Bằng chứng:** Cả năm agent dùng cùng loader/client contract; Ruff, Mypy và 21 test cùng PASS.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng:** Nhiều output có `affected_entities.order_ids=[]` dù order tồn tại; Verifier vẫn PASS.
- **Tái hiện:** So sánh 50 output với kết quả rule engine và CSV; 44 file thiếu order ID, 22 file có item nhưng thiếu seller ID.
- **Nguyên nhân gốc:** Verifier dùng `selected.issubset(expected)`, nên tập rỗng luôn hợp lệ; Policy Qwen được phép tự rút gọn entity.
- **Cách xử lý:** Khóa `selected_entities`, yêu cầu Coordinator so sánh danh sách đầy đủ theo thứ tự và đổi Verifier sang equality; domain API không được bỏ entity candidates của Python tool.
- **Xác minh:** Hai test hồi quy cố tình bỏ Policy ID và domain candidate đều trả conflict; mô phỏng 50 case deterministic đạt 50 PASS.
- **Điều học được:** Kiểm tra tính hợp lệ của ID không đủ; output chấm điểm còn yêu cầu tính đầy đủ và lineage của ID.

## 7. Hiểu biết về luồng end-to-end

1. `main.py` dùng `OlistDataLoader` nạp/index database chỉ đọc, tạo structured API client và năm agent runner; Coordinator nhận từng case.
2. Ba domain agent chạy song song, đọc CSV theo quyền hạn và trả facts/entity/evidence có contract.
3. Coordinator kiểm tra identity và tổng tiền, sau đó tạo EvidenceBundle có digest.
4. Python Policy áp dụng rule ưu tiên; Qwen Policy trả structured result và confidence riêng.
5. Coordinator dựng draft; Verifier đọc lại CSV, policy và giới hạn output. PASS mới được ghi atomic.
6. Domain utilities giữ phép tính và ID nhất quán; LLM client đảm bảo JSON Schema và retry mà không để secret đi vào trace.
7. Trace ghi lineage của input, task, bundle, policy, draft và output; metadata ghi model/framework/runtime.

## 8. Cam kết của thành viên

- [x] Nội dung phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end và contract giữa các agent.
- [x] Tôi chỉ ghi kết quả kiểm thử đã được xác minh trong repo hiện tại.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo không sao chép nguyên văn báo cáo của thành viên khác.

**Họ và tên:** Trần Hoàng Quân

**Ngày xác nhận:** 2026-08-05
