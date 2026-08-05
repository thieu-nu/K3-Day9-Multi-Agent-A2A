# Hướng dẫn chạy hệ thống

## 1. Yêu cầu môi trường

- Windows 10/11 với PowerShell.
- Python `3.12`.
- `uv` để cài Python và khóa dependency theo `uv.lock`.
- Khoảng 500 MB dung lượng trống cho môi trường Python.
- Không cần API key để chạy batch 50 case chính thức.

Tất cả lệnh bên dưới phải được chạy tại thư mục gốc repository:

```powershell
cd D:\AI_Thuc_Chien\lab\lab_09\K3-Day9-Multi-Agent-A2A
```

## 2. Cài đặt lần đầu

### Cách A - Máy hiện tại đã có uv trong repository

Kiểm tra:

```powershell
.\.tools\uv\uv.exe --version
```

Cài đúng Python và toàn bộ dependency:

```powershell
.\.tools\uv\uv.exe python install 3.12
.\.tools\uv\uv.exe sync
```

### Cách B - Máy mới chưa có uv

Cài `uv` bằng PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Mở lại PowerShell, sau đó chạy:

```powershell
uv python install 3.12
uv sync
```

Kiểm tra môi trường vừa tạo:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -c "import langgraph, polars, pydantic, together; print('dependencies: ok')"
```

Kết quả Python phải là phiên bản `3.12.x`.

## 3. Cấu hình Together/Qwen tùy chọn

Batch chính dùng CSV và rule engine deterministic nên không cần gọi API. Chỉ cấu hình bước này
khi muốn sử dụng adapter structured-output `Qwen/Qwen3.5-9B`.

Tạo `.env` từ file mẫu:

```powershell
Copy-Item .env.example .env
notepad .env
```

Nội dung:

```dotenv
TOGETHER_API_KEY=<your-together-api-key>
```

Không commit `.env` và không đưa API key vào source, trace hoặc metadata.

Smoke test API:

```powershell
@'
import asyncio
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict
from utils.llm_client import TogetherStructuredClient

class SmokeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: str

async def main():
    load_dotenv()
    result = await TogetherStructuredClient(max_retries=0).complete_structured(
        system_prompt="You are an API connectivity checker.",
        user_prompt='Return one JSON object whose status is "ok".',
        response_model=SmokeResult,
        schema_name="smoke_result",
        max_tokens=32,
    )
    print(result.model_dump_json())

asyncio.run(main())
'@ | .\.venv\Scripts\python.exe -
```

Kết quả mong đợi:

```json
{"status":"ok"}
```

## 4. Chạy kiểm tra source code

Chạy toàn bộ test:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Kết quả hiện tại:

```text
15 passed
```

Chạy format check, lint và strict type-check:

```powershell
.\.venv\Scripts\ruff.exe format --check tests main.py agents utils
.\.venv\Scripts\ruff.exe check tests main.py agents utils
.\.venv\Scripts\mypy.exe tests main.py agents utils
```

## 5. Chạy batch 50 case

Đảm bảo thư mục `input/` có đúng các file từ `EC_001.json` đến `EC_050.json`, sau đó chạy:

```powershell
.\.venv\Scripts\python.exe main.py
```

Quá trình chạy sẽ:

1. Đọc và index các CSV trong `data/` bằng Polars.
2. Giữ nguyên output cũ; mỗi case PASS sẽ atomic-overwrite đúng file cùng tên.
3. Truncate `logging/trace.jsonl`.
4. Chạy Order/Seller, Payment và Delivery Agent cho từng case.
5. Python áp dụng bảng policy `EC_POLICY_V1` theo đúng priority trong README, sau đó mới gọi Policy Agent
   Qwen. Rule/refund/action và bundle identity do Python khóa; Qwen đánh giá confidence và chọn
   entity/evidence. Kết quả API sửa trường bị khóa sẽ trả `POLICY_API_MISMATCH` và retry có giới hạn.
6. Tạo draft và chuyển sang Verifier Agent.
6. Chỉ ghi output khi Verifier trả `PASS`.
7. Ghi metadata của lượt chạy mới vào `logging/metadata.json`.

Nếu bất kỳ case nào thất bại, batch trả exit code `1` nhưng giữ nguyên mọi output đã có. Các case PASS
trong lượt hiện tại vẫn được ghi; file cũ của case FAIL cũng không bị xóa. Dùng trace và exit code để phân biệt
artifact của lượt hiện tại với file còn lại từ lượt trước.

### Chạy luồng Qwen API thực tế

Sau khi đã cấu hình `TOGETHER_API_KEY` trong `.env`, chạy:

```powershell
.\.venv\Scripts\python.exe main.py --use-api
```

Chạy lại một case duy nhất bằng API:

```powershell
.\.venv\Scripts\python.exe main.py --use-api --case EC_002
```

`--case` chỉ atomic-overwrite output cùng tên khi PASS và không xóa bất kỳ output nào khi FAIL. Trace và
metadata được tạo mới cho lượt chạy đơn; ba count trong metadata sẽ bằng `1` khi thành công.

Chế độ này thực hiện luồng hybrid có kiểm chứng:

1. Mỗi agent đọc CSV hoặc áp rule bằng code xác định.
2. Kết quả tool được gửi thật tới `Qwen/Qwen3.5-9B` làm context qua Together API.
3. Qwen sinh lại toàn bộ facts, entity, evidence, policy decision hoặc verification theo schema riêng.
4. Coordinator sử dụng chính JSON do Qwen trả về; kết quả tool không được trả thẳng làm AgentResult.
5. Qwen phải trả đúng `agent_name`, `task_id`, SHA-256 digest và schema Pydantic của agent.
6. Verifier vẫn tính lại dữ liệu độc lập trước khi cho phép ghi output.

Một batch không retry gọi API khoảng `5 agent x 50 case = 250` lần. Lượt chạy có thể mất vài phút,
phát sinh chi phí Together và phụ thuộc rate limit của tài khoản. `logging/metadata.json` sẽ ghi mode
`qwen_api_generated`; mỗi event `agent_completed` trong trace sẽ ghi model API đã dùng.

Structured result dùng tối đa 2048 output tokens. Nếu provider trả JSON bị cắt hoặc không parse được,
client tự gọi lại tối đa hai lần; Coordinator vẫn giữ retry riêng cho lỗi API/agent sau đó.

## 6. Kết quả sau khi chạy

Các artifact chính:

```text
output/EC_001.json ... output/EC_050.json
logging/trace.jsonl
logging/metadata.json
```

Kiểm tra số output:

```powershell
(Get-ChildItem output -Filter 'EC_???.json').Count
```

Kết quả phải là:

```text
50
```

Kiểm tra số event trace:

```powershell
(Get-Content logging\trace.jsonl).Count
```

Với batch không retry, kết quả hiện tại là `850` event.

Xem phân bố kết quả:

```powershell
Get-ChildItem output -Filter 'EC_???.json' |
    ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json } |
    Group-Object { $_.assessment.primary_issue } |
    Sort-Object Name |
    Select-Object Name, Count
```

Phân bố hiện tại:

```text
canceled_order_paid          8
late_delivery_logistics      8
late_delivery_seller         8
unavailable_order_paid       8
unsupported_late_claim       9
valid_split_payment          9
```

## 7. Chạy với đường dẫn khác

`--root` phải trỏ tới thư mục chứa `input/`, `data/`, `output/` và `logging/`:

```powershell
.\.venv\Scripts\python.exe main.py --root D:\path\to\repository
```

Có thể đổi số lượng case mong đợi khi `--root` trỏ tới một workspace thử chỉ chứa đúng số case đó:

```powershell
.\.venv\Scripts\python.exe main.py --root D:\path\to\six-case-workspace --expected-count 6
```

## 8. Đóng gói output để nộp

Sau khi batch thành công:

```powershell
Compress-Archive -Path output\EC_*.json -DestinationPath submission.zip -Force
```

Kiểm tra zip:

```powershell
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path submission.zip))
$zip.Entries | Select-Object FullName, Length
$zip.Dispose()
```

Zip phải có đúng 50 JSON ở root, không chứa `.env`, source code, trace hoặc metadata.

## 9. Lỗi thường gặp

### Không tìm thấy `.venv`

Chạy lại:

```powershell
uv sync
```

Hoặc trên máy hiện tại:

```powershell
.\.tools\uv\uv.exe sync
```

### Sai phiên bản Python

```powershell
uv python install 3.12
uv sync --refresh
```

### Thiếu CSV hoặc input

Không đổi tên file trong `data/`. Kiểm tra:

```powershell
(Get-ChildItem data -Filter '*.csv').Count
(Get-ChildItem input -Filter 'EC_???.json').Count
```

Kết quả tương ứng phải là `9` và `50`.

### API trả lỗi xác thực

Kiểm tra `.env` có đúng tên biến `TOGETHER_API_KEY`. Không thêm dấu nháy hoặc khoảng trắng quanh key.
Lỗi API không ảnh hưởng batch deterministic chạy bằng `main.py`.

### PowerShell chặn activate script

Không cần activate virtual environment. Dùng trực tiếp executable như trong tài liệu:

```powershell
.\.venv\Scripts\python.exe main.py
```
