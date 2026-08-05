# Member Role Report — Day 9: Multi Agent A2A (Olist E-commerce Investigation System)

> Báo cáo chi tiết vai trò, trách nhiệm, kỹ thuật triển khai và mức độ thấu hiểu đối với luồng toàn cục của kiến trúc Multi-Agent Agent-to-Agent (A2A).

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| :--- | :--- |
| **Họ và tên** | Đàm Minh Tuấn |
| **MSSV** | 2A202601169 |
| **Khóa/Lớp** | K3 |
| **Vai trò chính** | Developer — Phụ trách mô-đun `Payment Agent` & Tiện ích tải dữ liệu `OlistDataLoader` |
| **Ngày hoàn thành** | 2026-08-05 |

---

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu trực tiếp

| Module / Deliverable | File / Hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| :--- | :--- | :--- | :--- | :--- |
| **Payment Agent** | `agents/payment_agent.py` — Lớp `PaymentAgent` (hàm `process_task`, `_quantize_brl`, `_make_error`, `_create_base_result`) | Hợp đồng `AgentTask` từ Coordinator (chứa `lookup_order_id`, `reconciliation_tolerance_brl`) | Hợp đồng `AgentResult` chuẩn (chứa `facts`, `entity_candidates`, `evidence_candidates`, `errors`) | **Hoàn thành 100%** |
| **Data Loader Module** | `utils/data_loader.py` — Lớp `OlistDataLoader` (hàm `get_order_payments`, `get_order_items`, cache bộ nhớ) | Các file CSV trong thư mục `data/` (`olist_order_payments_dataset.csv` & `items`) | Hai danh sách từ điển (`List[dict]`) độc lập rành mạch cho payments và items, giữ nguyên 100% kiểu string | **Hoàn thành 100%** |
| **Automated Test Suite (TDD)** | `tests/test_data_loader.py` & `tests/test_payment_agent.py` | Bộ dữ liệu giả lập (mock temp CSVs) & tích hợp file thực tế | 12 Unit & Integration test cases tự động hóa khắt khe theo phương pháp TDD | **Hoàn thành 100%** |
| **Technical Specification & Planning** | `specs/payment_agent_spec.md`, `tasks/plan.md`, `tasks/todo.md` | Bản mô tả kiến trúc `architecture.md` & yêu cầu Python 3.11 | Tài liệu đặc tả kỹ thuật mô-đun, kế hoạch phân chia tiến độ và danh sách công việc (Checklist) | **Hoàn thành 100%** |

*Ghi chú: Chỉ nhận ownership cho mô-đun nghiệp vụ thanh toán (Payment Agent) và nền tảng dữ liệu cho agent này, tuân thủ nguyên tắc cách ly trách nhiệm trong kiến trúc A2A.*

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên / Module được hỗ trợ | Kết quả |
| :--- | :--- | :--- |
| **Thiết kế tiện ích truy xuất dữ liệu chung** | Hỗ trợ `Order Agent` & `Seller Agent` (nhóm domain) | Cung cấp sẵn cơ cấu đọc, khóa chỉ đọc (read-only) và bẫy bộ nhớ đệm theo ID trong `OlistDataLoader`, giúp các agent bên ngoài dễ dàng kế thừa mà không phải parse CSV lặp lại hay làm gheney hại dữ liệu gốc. |
| **Chuẩn hóa đối tượng báo lỗi có cấu trúc** | Hỗ trợ `Coordinator Agent` & `Verifier Agent` | Mẫu error formatting `_make_error` trong `PaymentAgent` trả ra chuỗi cấu trúc chuẩn: `code`, `path`, `message`, `source`, `retryable`, `retry_target` làm biểu mẫu chung để Coordinator quyết định retry hay dừng thi hành. |

---

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File / Hàm / Artifact liên quan | Kết quả bàn giao | Cách xác minh |
| :--- | :--- | :--- | :--- |
| Xây dựng tầng tải dữ liệu chỉ đọc, chống tích Descartes, bẫy O(1) in-memory cache | `utils/data_loader.py` | Mô-đun đọc dữ liệu an toàn, không can thiệp/ghi vào thư mục `data/`, giữ mọi định danh dạng `str` | Lệnh: `python -m unittest tests/test_data_loader.py -v` (4/4 tests PASS) |
| Triển khai logic tính toán tài chính chuẩn xác tuyệt đối (Financial Determinism) | `agents/payment_agent.py` | Kết quả `payment_total_brl`, `expected_total_brl`, `difference_brl` làm tròn chuẩn 2 số theo `ROUND_HALF_UP` | Lệnh: `python -m unittest tests/test_payment_agent.py -v` (8/8 tests PASS) |
| Xử lý trọn gói 5 trường hợp biên và báo cấu trúc lỗi `data_error` / `conflict` | `agents/payment_agent.py` | Agent xử lý thành công cờ `is_reconciled`, `is_split_payment`, chống lỗi trùng sequential, tiền âm, sai lệch chéo | Lệnh: `python -m unittest discover -s tests -v` (12/12 tests PASS) |

### Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

Khi chạy lượt kiểm thử toàn diện trên môi trường thực tiễn với **Python 3.11**, đầu ra console chứng minh chất lượng bàn giao đạt điểm số tuyệt đối, tốc độ kiểm thử chỉ mất khoảng 0.267 giây cho cả việc đọc dữ liệu tích hợp thực và giả lập biên:

```text
test_get_order_items (test_data_loader.TestOlistDataLoader.test_get_order_items) ... ok
test_get_order_payments (test_data_loader.TestOlistDataLoader.test_get_order_payments) ... ok
test_integration_with_real_data (test_data_loader.TestOlistDataLoader.test_integration_with_real_data) ... ok
test_no_cartesian_product_and_empty_order (test_data_loader.TestOlistDataLoader.test_no_cartesian_product_and_empty_order) ... ok
test_cross_check_conflict_with_order_seller (test_payment_agent.TestPaymentAgentEdgeCases.test_cross_check_conflict_with_order_seller) ... ok
test_duplicate_payment_sequential (test_payment_agent.TestPaymentAgentEdgeCases.test_duplicate_payment_sequential) ... ok
test_empty_order_payments (test_payment_agent.TestPaymentAgentEdgeCases.test_empty_order_payments) ... ok
test_invalid_unparseable_payment_value (test_payment_agent.TestPaymentAgentEdgeCases.test_invalid_unparseable_payment_value) ... ok
test_negative_payment_value (test_payment_agent.TestPaymentAgentEdgeCases.test_negative_payment_value) ... ok
test_reconciliation_within_tolerance (test_payment_agent.TestPaymentAgentStandard.test_reconciliation_within_tolerance) ... ok
test_split_payment (test_payment_agent.TestPaymentAgentStandard.test_split_payment) ... ok
test_standard_reconciled_payment (test_payment_agent.TestPaymentAgentStandard.test_standard_reconciled_payment) ... ok

----------------------------------------------------------------------
Ran 12 tests in 0.267s

OK
```

---

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết
1. **Sai số dấu phẩy động tài chính:** Hệ thống điều tra các ca tranh chấp thanh toán thương mại điện tử Olist (ví dụ: giao dịch chia nhỏ nhiều kỳ hạn hoặc trả qua voucher + thẻ). Việc dùng kiểu số floating-point (`float`) truyền thống để cộng dồn sẽ gây sai số tích lũy thảm họa ($0.1 + 0.2 \neq 0.3$), khiến cờ đối soát (`is_reconciled`) bị phán quyết sai khi so sánh với ngưỡng dung sai (`reconciliation_tolerance_brl = 0.10`).
2. **Bội diễn dữ liệu do join mảng 1:N thô:** Trong Olist, một đơn hàng `order_id` có thể có 5 món hàng (`items`) và 3 khoản thanh toán (`payments`). Nếu thực hiện join gộp thô hai bảng theo `order_id`, cơ sở dữ liệu sẽ sinh ra tích Descartes gồm $5 \times 3 = 15$ bản ghi ảo, khiến tính tổng tiền bị gấp đôi gấp ba.
3. **An toàn bảo vệ nguyên trạng dataset:** Mọi rò rỉ mã cho phép mở chế độ ghi (`w` / `a`) hay tùy tiện chỉnh sửa file trong thư mục `data/` đều vi phạm tính toàn vẹn kiểm toán (audit integrity).

### Cách triển khai (Giải pháp Kỹ thuật & Thuật toán)
- **Financial Determinism (Kiểu số thập phân tĩnh):** Trừ lùi toàn bộ phép toán về đối tượng `decimal.Decimal`. Trước khi làm quy tròn, tính tổng trên chuỗi vô tuyến: `sum(Decimal(str(val)))`. Sau đó thi hành hàm `_quantize_brl()` áp dụng chuẩn làm tròn ngân hàng ngược (`ROUND_HALF_UP`) về đúng 2 chữ số thập phân (`Decimal('0.01')`), sau đó mới xuất sang mảng JSON under-the-hood dưới dạng số để đảm bảo khả năng serialize.
- **Tác vụ chống tích Descartes (Anti-Cartesian Separation):** Xây dựng hai luồng tra cứu hoàn toàn độc lập trong `OlistDataLoader`. Phân tán dữ liệu thành hai list riêng: `get_order_payments()` và `get_order_items()`. Không bao giờ chắp vá 2 danh sách này với nhau. 
- **Quy tắc đếm `payment_count`:** Đếm chính xác dựa trên số lượng bản ghi thanh toán trả về (`len(payment_rows)`), tuyệt đối không đếm theo cờ kỳ hạn thanh toán (`payment_installments`), tuân thủ mục 8.3 của tài liệu kiến trúc.
- **Bảo hiểm giới hạn hợp đồng:** Ép chặt danh sách đầu ra của `entity_candidates.payment_ids` tối đa 5 giá trị duy nhất, và `evidence_candidates` tối đa 10 giá trị duy nhất mang cờ định danh `payment:<order_id>:<seq>`.
- **Hệ thống phòng vệ linh hoạt (Edge Case Defense):** Bố trí cờ bẫy trùng lặp `seen_sequentials` bằng cấu trúc dữ liệu `set()`. Bẫy tiền âm (`< Decimal("0.00")`), và bắt lỗi parse sai chuỗi để lập tức chặn đứng quá trình thực thi, chuyển sang `status = "data_error"` hoặc `status = "conflict"`.

### Input, Output và Contract

| Thành phần | Mô tả cấu trúc và Ràng buộc |
| :--- | :--- |
| **Input (`AgentTask`)** | Object JSON tuân thủ phong bì hợp đồng chứa: `contract_version: "1.0"`, `policy_version: "EC_POLICY_V1"`, `order_id` (kiểu chuỗi) và phần `payload`: `{"lookup_order_id": "<ID>", "reconciliation_tolerance_brl": 0.10}`. |
| **Output (`AgentResult`)** | Object JSON mang 11 trường hợp đồng: `status` (`success` \| `invalid_input` \| `data_error` \| `conflict`), `facts` (trường từ điển chứa 9 thông số đối soát tài chính), `entity_candidates`, `evidence_candidates`, `errors`, `warnings`. |
| **Module Phụ thuộc** | Phụ thuộc vào `utils/data_loader.py` để tra cứu file `olist_order_payments_dataset.csv` và `olist_order_items_dataset.csv` từ thư mục `data/`. |
| **Module Sử dụng output** | `Coordinator Agent` (để gõ nhịp nhào lặn bằng chứng), `Policy Agent` (đọc `facts.is_reconciled` và `difference_brl` để phán quyết chính sách bồi thường/chấp thuận). |
| **Điều kiện lỗi xử lý** | 1) `ORDER_ID_MISMATCH` (ID envelope không khớp payload); 2) `DUPLICATE_PAYMENT_SEQUENTIAL` (trùng số thứ tự thanh toán); 3) `NEGATIVE_PAYMENT_VALUE` (tiền âm); 4) `INVALID_PAYMENT_VALUE` (lỗi parse text); 5) `CROSS_CHECK_CONFLICT` (thông số tổng đối chiếu với Seller/Order Agent bị sai lệch). |

### Cách xác minh

```bash
python -m unittest discover -s tests -v
```

- **Kết quả mong đợi:** Tất cả 12 ca kiểm thử (bao hàm test_data_loader và test_payment_agent) trả về `ok`. Không xuất hiện bất kỳ ngoại lệ nào hoặc xung đột kỵ khí khi nạp dữ liệu thật.
- **Kết quả thực tế:** Toàn bộ test suite chạy hoàn hảo trong 0.267s với lời giải `Ran 12 tests in 0.267s — OK` trên lõi Python 3.11.
- **Artifact / log:** Code thực nghiệm và test runner đều lưu trữ trọn vẹn tại [tests/test_payment_agent.py](file:///d:/Coding/VinAI/K3-Day9-Multi-Agent-A2A/tests/test_payment_agent.py) và [tests/test_data_loader.py](file:///d:/Coding/VinAI/K3-Day9-Multi-Agent-A2A/tests/test_data_loader.py), hoàn toàn vô trùng với `.env`, không lộ chìa khóa bí mật hay secret nào.

---

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Khi xây dựng mô-đun `OlistDataLoader` phục vụ tra cứu lặp đi lặp lại hàng nghìn ca `case_id` cho hệ thống, tập dữ liệu gốc Olist CSV rất to lớn (file thanh toán và sản phẩm lên đến hàng chục vạn dòng). Việc xử lý I/O đọc file cơ học trên mỗi lần agent thi hành sẽ khiến bottleneck về hiệu năng là vô cùng tai hại.
- **Các phương án đã cân nhắc:**
  1. *Phương án 1:* Mỗi lần `get_order_payments()` được gọi, mở file CSV với `open()`, duyệt từng dòng với `csv.DictReader` và lọc trả ra kết quả. (Ít tốn RAM nhưng thời gian thực thi tỷ lệ thuận theo số lượt gọi O(N * M)).
  2. *Phương án 2:* Nạp toàn bộ CSV và chắp nối thành một bảng dữ liệu gộp khổng lồ trong bộ nhớ hoặc dùng Pandas dataframe để gia tăng tốc độ, có thể sinh thêm các file cache tạm kiểu `.csv` hoặc `.parquet` vào folder `data/` cho nhanh.
  3. *Phương án 3:* Thiết kế cơ chế **Lazy Loading In-Memory Index (Bộ đệm nhàn rỗi O(1))**. Khi và chỉ khi truy vấn đầu tiên được phát động, DataLoader tải CSV 1 lần bằng `csv.DictReader`, lập chỉ mục theo khóa `order_id` lưu vào hai từ điển Python độc lập in-memory `_payments_cache` và `_items_cache` (không động chạm disk), các lần truy vấn tiếp theo mang lại thời gian tra cứu O(1).
- **Phương án đã chọn:** **Phương án 3** — Lazy Loading In-Memory Index theo cấu trúc từ điển native của Python.
- **Lý do (Trade-off):** 
  - *Correctness & Security:* Phương án 2 có nguy cơ cao làm ô nhiễm thư mục `data/` (vi phạm yêu cầu #2 là bất khả xâm phạm data gốc) hoặc vi phạm quy định không join mảng 1:N. Dùng từ điển native giúp giữ hoàn toàn các ID dạng chuỗi (`str`) mà không sợ Pandas tự ý chuyển "001" thành số `1` hoặc số `NaN`.
  - *Performance vs Complexity:* Bộ dữ liệu 100.000 dòng chiếm dưới 25MB trong bộ nhớ RAM (hoàn toàn an toàn và nhẹ), bù lại thời gian chạy giảm từ vài phút cho cả nghìn case về mức 0.22 giây.
- **Bằng chứng quyết định phù hợp:** Trong ca kiểm thử `test_integration_with_real_data`, hệ thống lập tức mở rộng tra cứu thẳng vào thư mục `data/` thật của dự án và nhặt ra khoản thanh toán `99.33` BRL cho đơn hàng `b81ef226...` chỉ trong vài phần nghìn giây.

---

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng / lỗi nguyên văn:** 
  Khi thực thi pha RED theo phương pháp TDD cho các trường hợp biên của Payment Agent, hệ thống báo lỗi vi phạm logic kiên trì khi phát hiện dữ liệu thô lọt vào vòng tra cống hiến:
  ```text
  FAIL: test_duplicate_payment_sequential (tests.test_payment_agent.TestPaymentAgentEdgeCases.test_duplicate_payment_sequential)
  AssertionError: 'success' != 'data_error'
  - success
  + data_error
  ```
- **Lệnh hoặc bước tái hiện:** Chạy lệnh bash: `python -m unittest tests/test_payment_agent.py -v` sau khi thêm tập mẫu thử với file CSV cố ý dàn dựng 2 dòng chứa cùng chỉ mục `payment_sequential = 1` cho một đơn hàng.
- **Nguyên nhân gốc (Root Cause):** Mã code khung hiện tại ở vòng lặp thanh toán `for row in sorted_payments:` chỉ quan tâm đến việc parse ra giá trị tiền, thực thi phép cộng số, và gom nhặt vào danh sách `payments_list`. Hệ thống vắng bóng cơ chế gác ngục (gatekeeper) theo dõi các mảng chỉ mục đã đi qua, dẫn đến việc nuốt trọn dữ liệu lặp, tự coi đơn hàng thành công (`success`), vi phạm nghiêm trọng tài liệu kiến trúc quy định: *Khi dữ liệu thanh toán bất thường hoặc trùng seq, Agent buộc phải dừng lại, báo cờ data_error và không được giả lập facts*.
- **Cách xử lý:** 
  1. Thêm tập lưu trữ duy nhất `seen_sequentials = set()` trước vòng lặp xử lý từng giao dịch.
  2. Tại đầu dòng vòng lặp, kiểm định tường minh cờ lặp:
  ```python
  if seq in seen_sequentials:
      result["status"] = "data_error"
      result["errors"].append(self._make_error("DUPLICATE_PAYMENT_SEQUENTIAL", f"payments[{seq}]", f"Trùng lặp payment_sequential {seq} trong order {order_id}"))
      return result
  seen_sequentials.add(seq)
  ```
  3. Áp dụng kỹ thuật ngắt lập tức (short-circuit exit), giữ nguyên trường `facts = {}` (rỗng) nhằm tuân thủ nguyên tắc không bịa đặt sự kiện khi agent lỗi.
- **Cách xác minh sau khi sửa:** Thực hiện rerun lệnh `python -m unittest tests/test_payment_agent.py -v`. Trạng thái thông báo thay đổi sang `test_duplicate_payment_sequential ... ok` (GREEN Phase).
- **Điều học được:** Trong thiết kế Multi-Agent điều tra tự động, "ngăn chặn lỗi sớm" (Fail-Fast) là chìa khóa vàng. Một Domain Agent có phẩm chất tốt là agent biết nói "Không" (trả `data_error`, `conflict`) một cách có cấu trúc rõ ràng khi thấy dữ liệu đầu vào nhiễm bẩn, chứ không được nỗ lực bẻ cong sai lệch thành kết quả đúng giả lập để tâng công với Coordinator.

---

## 7. Hiểu biết về luồng end-to-end

Trình bày khả năng thấu hiểu kiến trúc tổng thể của hệ thống **Day 9: Multi-Agent A2A Olist Investigation System**:

#### 1. Luồng dữ liệu và Điều phối (Orchestration & Data Flow) diễn ra trong toàn pipeline thế nào?
**Trả lời:** Mọi sự việc xuất hành từ `Coordinator Agent` khi đọc vào một hồ sơ tranh chấp từ file `input/<case_id>.json`. Coordinator đóng vai trò trung tâm nhạc trưởng, đọc thư mục dữ liệu thô, sau đó **song song song song** ném các gói hợp đồng `AgentTask` xuống 3 Domain Agents độc lập: `Order Agent`, `Payment Agent`, và `Seller & Shipping Agent`. Các Domain Agents không giao tiếp thẳng với nhau mà thi hành logic nghiệp vụ độc lập, đọc dữ liệu của phần mình và gởi trả gói bằng chứng `AgentResult` ngược về cho Coordinator.

#### 2. Vai trò của hợp đồng dữ liệu (Contracts) và cách Policy Agent ra quyết định phán quyết ra sao?
**Trả lời:** Hợp đồng dữ liệu `AgentTask` và `AgentResult` chính là bức tường an toàn giữ cho các agent làm việc nhịp nhàng trên nền JSON Schema khắt khe (luôn kèm cờ `contract_version`, `policy_version`, `status` và `errors`). Ngay sau khi Coordinator tập hợp đủ 3 mảnh ghép bằng chứng từ 3 domain agents vào một khối `EvidenceBundle`, khối này lập tức chuyển tới `Policy Agent`. Policy Agent sẽ là chốt chặn lý luận nghiệp vụ, căn cứ vào các sự kiện thực đắc (`facts` như `is_reconciled`, cờ vỡ nén giao hàng) để thi hành cây từ khóa chính sách, quyết định số tiền hoàn trả/phạt hay gán nhãn trạng thái quyết định (`decision`), đi kèm với mức độ tự tin (`confidence: "high" | "medium" | "low"`).

#### 3. Khác biệt tường minh nhất giữa các file log trong `logging/` và kết quả nộp bài ở `output/` là gì?
**Trả lời:** Thư mục `logging/` mang tính năng của một **bộ đè chóp hậu trường kiểm toán (Audit Trail)**, nơi chứa `trace.jsonl` (lưu lại rành mạch lịch sử giao nhận, từng tin nhắn handoff, các bước retry và giải trình nguyên do loại trừ luật) cùng `metadata.json` (chứa khai báo danh tính model AI, dung lượng $\le 10\text{B}$ tham số và các tổng số thống kê batch). 
Ngược lại, thư mục `output/` là **khung nộp bài cuối cùng (Clean Final Output)**, tuyệt đối không cho phép gõ kèm vết log, trace, error detail hay trường `run_id`. Mỗi file ở output như `output/<case_id>.json` phải tuân thủ chuẩn duy nhất theo yêu cầu hệ thống chấm điểm tự động.

#### 4. Vì sao hệ thống bắt buộc sử dụng kiểu `Decimal` trong Python và ngăn cản hoàn toàn thao tác join bảng 1:N?
**Trả lời:** Kiểu `Decimal` được dùng để đạt độ vô trùng tài chính tuyệt đối (Zero-Tolerance Arithmetic Approximation), triệt tiêu các lỗi làm tròn vô thức mà cỗ máy nhị phân gây ra khi cộng trừ tiền BRL dưới định dạng `float`. Trong khi đó, việc phong tỏa thao tác join thô giữa các bảng 1:N (như một đơn hàng có nhiều khoản thanh toán và nhiều chi nhánh hàng hóa) chính là áo giáp chống sự nhân lên theo hàm tích Descartes (Cartesian Explosion). Điều này đảm bảo khi hệ thống gom bằng chứng và đếm số giao dịch (`payment_count`) thì kết quả trả ra chính là số nguyên trạng hàng giao dịch minh bạch từng dòng một.

#### 5. Một lượt xử lý (case) được xem là hoàn thành thành công dựa vào cờ kiểm duyệt nào và bởi agent nào?
**Trả lời:** Quyền phán quyết cao nhất đối với một lượt xử lý thành công thuộc về quyền lực cai trị của **`Verifier Agent`**. Sau khi `Policy Agent` kết thúc ý kiến ra bản chiết nạp, gói dữ liệu được tống chuyển đến `Verifier Agent`. Verifier thi hành đợt kiểm tra chéo cuối cùng (Cross-validation): rà soát từ vựng JSON schema, kiểm nghiệm sự trùng khớp chéo dữ liệu giữa các agent và thẩm quyền bồi thường, tháo gỡ các đầu mối `payment_ids` / `evidence_candidates` mâu thuẫn. Một ca điều tra chỉ chính thức bước lên ngai thành công (để từ đó được cấp giấy thông hành ghi file xuống thư mục `output/`) khi và chỉ khi `Verifier Agent` đóng cờ hợp đồng `"status": "PASS"`.

---

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra kỹ lưỡng sự thực thấu suốt trên repository:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Đàm Minh Tuấn  
**Ngày xác nhận:** 2026-08-05
