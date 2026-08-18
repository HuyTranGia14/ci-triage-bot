# M0 — Nền móng dự án

*Hướng dẫn thực hành. Bạn tự gõ, tôi giải thích tại sao. Không có code viết sẵn ở đây — chỉ có yêu cầu, lý do, và cách tự kiểm chứng.*

---

## Phần 0 — Đọc design doc xong: 6 vấn đề bạn phải xử lý TRƯỚC khi code

Đây là bài học đầu tiên và quan trọng nhất của môn Công nghệ phần mềm: **design document nào cũng có mâu thuẫn.** Việc của kỹ sư không phải là code mù theo tài liệu, mà là đọc nó với con mắt phản biện, tìm ra chỗ vênh, và **ghi lại quyết định của mình** — chứ không im lặng tự chọn một bên.

Tôi tìm được 6 chỗ. Bạn sẽ ghi tất cả vào `docs/design-issues.md` trong task M0-9.

### ❶ Màn Triage Detail cần dữ liệu mà database không hề lưu — NGHIÊM TRỌNG

Mục 5.2.2 nói màn Triage Detail hiển thị: *raw webhook payload, trimmed log, prompt gửi Claude, JSON response nhận về*. Mục 3.2.11 `get_detail` cũng nói "Returns one result, **its trimmed log and raw JSON response**".

Nhưng bảng `triage_result` ở mục 4.1 **không có cột nào** chứa những thứ đó. Và mục 2 (Conceptual Model) khẳng định `WebhookPayload` "is never persisted".

→ Màn hình này **không thể hiện thực được** với data design hiện tại.
→ Bạn phải quyết: thêm cột (`trimmed_log`, `prompt_sent`, `raw_response`) vào `triage_result`, hay tách bảng phụ `triage_artifact`? Cân nhắc: log trimmed cỡ vài KB × N run — nhét vào bảng chính làm mọi query `list_recent()` nặng lên vô ích. Tôi nghiêng về bảng phụ, nhưng **quyết định là của bạn** và phải viết rõ lý do.

### ❷ Một secret hay nhiều secret? Và con gà — quả trứng

Mục 3.2.2: `SignatureVerifier.shared_secret : str` — **một** secret duy nhất.
Mục 3.2.14: `RepoManager.find_by_repo` — "used to select the **correct secret** for SignatureVerifier" — **secret theo từng repo**.

Hai mục này mâu thuẫn. Tệ hơn, phương án "secret theo repo" có vấn đề thứ tự: để biết dùng secret nào, bạn phải biết repo nào; để biết repo nào, bạn phải đọc body; nhưng body **chưa được xác thực**.

→ Đây không phải lỗ hổng bảo mật nếu bạn xử lý đúng: đọc `repository.full_name` từ body chưa tin cậy **chỉ để tra secret**, rồi verify HMAC trên toàn bộ raw body. Nếu kẻ tấn công đặt tên repo giả, nó sẽ tra ra secret khác (hoặc không có) và HMAC sẽ fail. An toàn — nhưng bạn phải **viết rõ lập luận này ra**, vì người chấm sẽ hỏi.
→ Hoặc chọn phương án đơn giản: một secret toàn cục cho mọi repo, đúng theo 3.2.2, và sửa lại mô tả của 3.2.14.

### ❸ Mục 3.2.8 và 3.2.9 mô tả prompt-only, nhưng mục 4.2 đã chốt tool-based

3.2.8 `ClaudeClient.complete` → "returns the raw assistant **text**"
3.2.9 `ResponseValidator.validate` → "**Extracts JSON from the model text**"

Nhưng 4.2 kết luận rõ: dùng tool-based, "the API returns an **already-parsed object**", và chính vì thế mà bước extraction "that tool-based avoids entirely".

→ 3.2.8/3.2.9 là tàn dư của bản nháp trước khi chạy spike. Đây là **lỗi tài liệu, không phải lỗi code**. Sửa lại spec: `complete()` trả `dict`, `validate()` nhận `dict`. Ghi vào design-issues rằng bạn đã sửa và tại sao.

### ❹ DTO `WebhookPayload` thiếu field mà pipeline bắt buộc phải có

Mục 3.2.16 khai báo đúng 4 field: `event`, `status`, `run_id`, `repo`.

Nhưng:
- `EventFilter` có thuộc tính `target_conclusion` → nó phải đọc `conclusion` từ payload. **Không có.**
- `TriageResult` có `pr_number` → phải lấy từ payload. **Không có.**
- `GitHubClient.get_run_details` trả head SHA → nhưng payload gốc đã có `head_sha`, và ta cần nó để resolve PR khi fork. **Không có.**

→ Đây là **thiếu sót thiết kế thật sự**, không phải mâu thuẫn. Bổ sung `conclusion`, `pr_number`, `head_sha` vào 3.2.16 và vào diagram.

### ❺ Bảng `triage_result` thiếu ràng buộc UNIQUE

Mục 3.2.13 nói `HistoryStore.save` phải "Idempotent on (repository_id, run_id)" — rất tốt, thiết kế đã nghĩ tới.
Nhưng DDL ở 4.1 chỉ có hai CHECK constraint, **không có UNIQUE(repository_id, run_id)**.

→ Tính idempotent chỉ nằm ở tầng ứng dụng thì không đủ: GitHub gửi lại webhook, hai request chạy song song, cả hai cùng check "chưa có" rồi cùng insert → 2 comment trùng trên PR. **Ràng buộc phải nằm ở database.** Bổ sung UNIQUE vào DDL và vào data diagram.

### ❻ Cơ chế "background" không được thiết kế ở đâu cả

Mục 3.2.1 nói WebhookController "dispatches background triage so the HTTP response returns inside GitHub's timeout window" — đúng, nhưng **không mục nào nói dispatch bằng cái gì**. Không có class nào chịu trách nhiệm hàng đợi, retry, hay khôi phục sau khi process chết.

→ Đây là chỗ bạn viết ADR đầu tiên: chốt phương án **bảng job trong SQLite + worker thread** (đã thống nhất ở phiên trước), giải thích tại sao không dùng Celery/Redis, và **bổ sung class mới vào class diagram** (ví dụ `JobQueue` hoặc `TriageWorker`). Class diagram từ 17 sẽ thành 18 class — và đó là điều bình thường, miễn là bạn ghi lại.

### Ngoài ra, hai điểm nhỏ cần thống nhất

- **Template Markdown:** mục 5.2.5 đưa ra một template có link "View full log" và "Report incorrect triage", **khác** template đang có trong `demo/comment.md`. Doc là hợp đồng → lấy 5.2.5 làm chuẩn. Nhưng `URL_TO_REPORT` trỏ đi đâu chưa ai định nghĩa — bạn cần chốt (gợi ý: trỏ về màn Triage Detail của dashboard).
- **Màn Settings lưu API key:** lưu key của Claude vào DB hoặc file cấu hình là rủi ro bảo mật. Chốt phương án: giá trị thật luôn đọc từ biến môi trường, màn Settings chỉ hiển thị dạng che (`sk-ant-•••••`) và cho biết key đã được nạp hay chưa. Ghi vào ADR.

**Nhiệm vụ của bạn ở phần này:** đọc lại 6 điểm trên, tự kiểm chứng bằng cách mở đúng mục trong PDF, rồi tự quyết. Đừng nhận quyết định của tôi mà không kiểm tra — đó cũng là một kỹ năng.

---

## Phần 1 — M0 là gì, và tại sao không được nhảy cóc

M0 không tạo ra tính năng nào. Nó tạo ra **khả năng biết mình sai ở đâu, một cách tự động.**

Ngay bây giờ, nếu bạn viết một hàm sai kiểu dữ liệu, không gì báo cho bạn biết. Nếu bạn xóa nhầm một file, không gì báo. Nếu code chạy trên máy bạn nhưng không chạy trên máy khác, bạn chỉ biết vào đúng buổi bảo vệ.

M0 dựng cái lưới an toàn đó **trước khi** có gì để rơi. Làm sau thì đau: bạn sẽ phải sửa 3000 dòng code cho vừa lint, thay vì sửa 3 dòng.

Thuật ngữ ngành gọi việc này là **shift-left**: đẩy việc phát hiện lỗi về càng sớm càng tốt trong vòng đời. Lỗi phát hiện lúc gõ code rẻ hơn lúc review, rẻ hơn lúc test, rẻ hơn nhiều lần lúc production.

---

## Phần 2 — 10 task

Làm theo thứ tự. Mỗi task tự kiểm chứng được — đừng qua task sau khi task trước chưa "xanh".

---

### ☐ M0-1 · Dọn line endings

**Vấn đề:** `git status` đang báo **29/29 file đã sửa** trong khi bạn chưa động vào file nào. Chạy `git diff CLAUDE.md` sẽ thấy 77 dòng thêm / 77 dòng xóa trên một file 78 dòng — nghĩa là Git coi *toàn bộ file* đã thay đổi.

**Nguyên nhân:** Windows kết thúc dòng bằng `CRLF` (`\r\n`), Linux/macOS và Git dùng `LF` (`\n`). Không khai báo gì thì mỗi lần checkout trên hệ điều hành khác, cả repo "thay đổi".

**Tại sao phải sửa trước mọi thứ khác:** nếu không, mọi PR sau này sẽ có 100% diff là nhiễu, và bạn sẽ không bao giờ review được thay đổi thật của mình. Đây là ví dụ điển hình của **signal-to-noise ratio** trong version control.

**Việc cần làm:**
1. Tạo file `.gitattributes` ở gốc repo.
2. Trong đó khai báo: mặc định mọi file văn bản dùng `text=auto eol=lf`; các đuôi nhị phân (`.png`, `.pdf`, `.pptx`, `.zip`, `.svg`? — cân nhắc, SVG là text) khai báo `binary` để Git không đụng vào.
3. Chạy `git add --renormalize .`
4. Commit một lần duy nhất, message dạng `chore: normalize line endings`.

**Tự kiểm chứng:** sau khi commit, `git status` phải sạch hoàn toàn. Nếu vẫn còn file "modified", bạn thiếu một đuôi file trong `.gitattributes`.

**Tra cứu:** `git help attributes`, tìm mục "eol".

---

### ☐ M0-2 · Quy ước nhánh và commit

**Tại sao solo vẫn cần:** môn học chấm **quy trình**, không chỉ sản phẩm. Một repo với 2 commit tên "Add demo, diagrams, spike" không chứng minh được gì về kỹ năng của bạn. Một repo với 40 commit theo Conventional Commits, mỗi commit gắn ticket, mỗi tính năng một nhánh — đó là bằng chứng.

Ngoài ra, đây là thói quen bạn sẽ dùng cả đời đi làm.

**Việc cần làm:**
1. Quy ước: **không commit trực tiếp lên `main`**. Mỗi ticket = một nhánh, đặt tên `<type>/NMCNPM-<số>-<mô-tả-ngắn>`.
2. Quy ước message theo **Conventional Commits**: `<type>(<scope>): <mô tả>`, với type ∈ {`feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`}.
3. Viết `CONTRIBUTING.md` ở gốc repo ghi lại 2 quy ước trên (ngắn thôi, 20–30 dòng). Đây là một artifact chấm được.
4. Bật branch protection cho `main` trên GitHub: Settings → Branches → yêu cầu PR trước khi merge, yêu cầu status check pass.

**Tự kiểm chứng:** thử `git push origin main` trực tiếp — GitHub phải từ chối.

**Tra cứu:** conventionalcommits.org

---

### ☐ M0-3 · Dựng khung thư mục theo `src` layout

**Hai kiểu bố cục Python:**

*Flat layout* — package nằm ngay ở gốc repo. Khi bạn chạy `pytest` từ gốc, Python tự thêm thư mục hiện tại vào đường dẫn import, nên code import được **kể cả khi package chưa được cài đúng cách**.

*Src layout* — package nằm trong `src/`. Python **không** tự thêm `src/` vào đường dẫn. Muốn import được thì bắt buộc phải cài package (`pip install -e .`).

**Tại sao chọn src layout:** nó buộc bạn test đúng thứ mà người dùng sẽ cài. Nếu bạn quên khai báo một sub-package trong `pyproject.toml`, flat layout vẫn chạy ngon trên máy bạn và vỡ trên máy người khác — kinh điển "works on my machine". Src layout vỡ ngay lập tức trên máy bạn. **Vỡ sớm là tính năng, không phải lỗi.**

**Việc cần làm:**
- Tạo `src/ci_triage/__init__.py`, trong đó khai báo một biến `__version__`.
- Tạo `tests/`.
- Tạo `docs/`.
- **Dừng ở đó.**

**Điểm quan trọng — đừng tạo sẵn 17 file rỗng cho 17 class.** Cám dỗ rất lớn: bạn có class diagram, cứ tạo hết cho "có cấu trúc". Đừng. Thư mục rỗng và file rỗng là **nợ kỹ thuật ngay từ ngày đầu**: chúng làm repo trông đã hoàn thành trong khi chưa có gì, làm bạn không biết cái nào thật cái nào giả, và mỗi lần bạn đổi ý về cấu trúc thì phải dọn cả đống.

Nguyên tắc gọi là **YAGNI** — *You Aren't Gonna Need It*. Tạo file khi bạn thật sự viết code vào nó, không sớm hơn.

Cấu trúc đích (từ TECH_BRIEF) là **bản đồ để đi**, không phải thứ phải dựng xong ngay hôm nay.

**Tự kiểm chứng:** `ls src/ci_triage` chỉ thấy `__init__.py`. Nếu thấy nhiều hơn, bạn đã scaffold quá sớm.

---

### ☐ M0-4 · `pyproject.toml`

**Tại sao có file này:** trước đây một dự án Python cần `setup.py` + `requirements.txt` + `setup.cfg` + `.flake8` + `pytest.ini` + `mypy.ini` — sáu file, sáu cú pháp. PEP 518 và PEP 621 gom tất cả vào một file TOML duy nhất.

**Các mục bạn cần khai báo:**

| Mục | Chứa gì | Lưu ý |
|---|---|---|
| `[build-system]` | công cụ build (hatchling hoặc setuptools) | chọn một, đừng phân vân |
| `[project]` | `name`, `version`, `requires-python`, `dependencies` | đặt `requires-python = ">=3.11"` |
| `[project.optional-dependencies]` | nhóm `dev` | tách bạch runtime và công cụ phát triển |
| `[tool.ruff]` | cấu hình lint | xem M0-6 |
| `[tool.mypy]` | cấu hình type check | xem M0-6 |
| `[tool.pytest.ini_options]` | cấu hình test | xem M0-6 |

**Quyết định cần chốt — tách dependencies làm hai nhóm:**

*Runtime* (thứ người dùng cần để chạy bot): fastapi, uvicorn, pydantic, pydantic-settings, sqlalchemy, httpx, anthropic, jinja2.

*Dev* (thứ chỉ bạn cần khi phát triển): pytest, pytest-cov, pytest-asyncio, respx, ruff, mypy.

**Tại sao phải tách:** nếu trộn chung, môi trường production sẽ cài cả pytest và mypy — vô ích, nặng, và mở rộng bề mặt tấn công. Đây là một nguyên tắc bạn sẽ gặp lại trong Docker multi-stage build.

**Về việc ghim phiên bản:** chưa cần ghim chính xác ở M0. Đặt giới hạn dưới hợp lý (ví dụ `fastapi>=0.115`) là đủ. Ghim tuyệt đối là việc của lockfile, và với đồ án này thì overkill.

**Tự kiểm chứng:**
```powershell
py -m pip install -e ".[dev]"
py -c "import ci_triage; print(ci_triage.__version__)"
```
Lệnh thứ hai phải in ra version. Nếu báo `ModuleNotFoundError`, `pyproject.toml` khai báo sai vị trí package — đó chính là lỗi mà src layout giúp bạn phát hiện ngay.

**Tra cứu:** packaging.python.org, mục "Writing your pyproject.toml".

---

### ☐ M0-5 · Môi trường ảo

**Tại sao:** máy bạn có một bản `python` MSYS2 hỏng (CLAUDE.md đã ghi). Ngoài ra `spike/` có venv riêng. Nếu cài thẳng vào Python hệ thống, sớm muộn bạn sẽ có xung đột phiên bản giữa spike và dự án chính, và không cách nào gỡ.

**Việc cần làm:**
1. Ở **gốc repo** (không phải trong `spike/`), tạo venv tên `.venv`.
2. Kích hoạt nó. Trên PowerShell là `.\.venv\Scripts\Activate.ps1` — nếu bị chặn bởi execution policy, tra cứu `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
3. Cài `pip install -e ".[dev]"` **bên trong venv đã kích hoạt**.

**Bẫy thường gặp:** quên activate rồi cài, thế là cài vào Python hệ thống. Cách kiểm tra: `where.exe python` (Windows) phải trỏ vào `.venv\Scripts\python.exe`.

**Tự kiểm chứng:** `pip list` chỉ thấy các package bạn vừa cài, không thấy rác từ hệ thống.

---

### ☐ M0-6 · Ba công cụ chất lượng

Đây là phần đáng học nhất của M0. Ba công cụ, ba loại lỗi khác nhau, bắt ở ba thời điểm khác nhau.

**Ruff — linter + formatter.** Bắt lỗi *phong cách và lỗi rõ ràng*: biến khai báo mà không dùng, import thừa, dòng quá dài, thứ tự import lộn xộn. Nó thay thế cả bộ black + isort + flake8 và nhanh hơn hàng chục lần.

Cấu hình: bật các nhóm rule `E` (pycodestyle), `F` (pyflakes), `I` (isort), `B` (flake8-bugbear — bắt các bẫy Python phổ biến như mutable default argument), `UP` (pyupgrade — gợi ý cú pháp hiện đại). Đặt `line-length` (88 hoặc 100, chọn một rồi đừng đổi).

**Mypy — static type checker.** Bắt lỗi *kiểu dữ liệu* trước khi chạy: bạn trả về `str` nhưng khai báo `int`, bạn gọi `.upper()` trên một biến có thể là `None`.

Cấu hình quan trọng: **đừng bật mức gắt nhất ngay.** Đặt `disallow_untyped_defs = true` cho `src/`, và **loại trừ `demo/` và `spike/`** — hai thư mục đó đang đóng băng, ép chúng qua mypy chỉ tạo nhiễu.

Lời khuyên: bắt đầu dễ, siết dần. Một dự án bật `strict = true` từ ngày đầu thường kết thúc bằng việc lập trình viên rắc `# type: ignore` khắp nơi — tệ hơn là không có mypy.

**Pytest — test runner.** Cấu hình: `testpaths = ["tests"]`, và bật đo coverage với `--cov=ci_triage`.

**Tự kiểm chứng:** chạy lần lượt cả ba trên repo gần như rỗng. Cả ba phải sạch. Nếu chưa sạch ngay từ lúc chưa có code, cấu hình sai.

---

### ☐ M0-7 · Test đầu tiên (và tại sao nó "vô nghĩa" nhưng cực kỳ quan trọng)

Viết một test kiểm tra rằng `ci_triage.__version__` là một chuỗi không rỗng.

Nghe ngớ ngẩn — test này không kiểm tra logic nghiệp vụ nào cả. Nhưng nó chứng minh **cả dây chuyền** đang hoạt động:

package được cài đúng → import được → pytest tìm thấy thư mục test → pytest chạy được → coverage đo được → và (sau M0-8) CI chạy được.

Khái niệm này gọi là **walking skeleton**: một đường xuyên suốt mỏng nhất có thể qua toàn bộ hệ thống, dựng trước, để mọi thứ sau đó chỉ là làm dày thêm. Nếu bạn viết 500 dòng code rồi mới dựng CI, bạn sẽ phải debug đồng thời cả code lẫn hạ tầng và không biết cái nào hỏng.

**Tự kiểm chứng:** `pytest` → `1 passed`.

---

### ☐ M0-8 · GitHub Actions CI

**Tại sao đây là task quan trọng nhất của M0 — và bạn sẽ thấy nó có hai công dụng.**

*Công dụng 1:* mọi lần push, một máy sạch sẽ cài lại dự án từ đầu và chạy lint + type check + test. Điều này bắt được cả một lớp lỗi mà máy bạn không bao giờ bắt được: thiếu dependency (vì máy bạn đã cài sẵn từ lâu), phụ thuộc vào đường dẫn Windows, file quên `git add`.

*Công dụng 2 — và đây là chỗ thú vị:* **dự án của bạn là một con bot đọc log CI. Bạn vừa tạo ra một CI để nó đọc.** Đến M2 bạn sẽ cần log GitHub Actions thật; bây giờ bạn đã có nguồn.

**Việc cần làm:**
1. Tạo `.github/workflows/ci.yml`.
2. Trigger: `push` và `pull_request` vào `main`.
3. Job chạy trên `ubuntu-latest`: checkout code → setup Python 3.11 (bật cache pip) → `pip install -e ".[dev]"` → chạy ruff → chạy mypy → chạy pytest.
4. Push lên một nhánh, mở PR, xem tab Actions.

**Bẫy thường gặp:** quên `actions/checkout` là bước đầu tiên; hoặc cài dependencies bằng `requirements.txt` không tồn tại thay vì `-e ".[dev]"`.

**Việc thứ hai, làm luôn hôm nay vì nó tốn 15 phút và M2 cần:** tạo một repo GitHub **riêng** tên `ci-triage-sandbox`, trong đó có một workflow **cố tình fail** (ví dụ một test pytest sai hiển nhiên), và một Pull Request đang mở. Đây sẽ là nguồn log thật cho M2 và nơi bot post comment thật. Đừng đặt workflow-fail này trong repo chính — repo chính phải luôn xanh.

**Tự kiểm chứng:** badge CI xanh trên PR của repo chính; và ở repo sandbox, tab Actions có một run đỏ với log tải về được.

---

### ☐ M0-9 · `docs/` và truy vết

**Tại sao đây là task ăn điểm mà hầu hết sinh viên bỏ qua:** người chấm cầm design document 42 trang và cầm repo code. Câu hỏi đầu tiên trong đầu họ là *"code này có đúng là hiện thực của tài liệu kia không?"*. Nếu họ phải tự đi tìm, bạn mất điểm. Nếu bạn đưa sẵn bảng đối chiếu, bạn được điểm.

**Việc cần làm:**

1. Copy file PDF design document vào `docs/`. Repo phải tự chứa được — người khác clone về là có đủ.

2. Viết `docs/traceability.md`: một bảng, mỗi dòng một class trong class diagram, các cột:

   | Class (mục trong doc) | Module dự kiến | File test | Trạng thái |
   |---|---|---|---|

   Trạng thái ban đầu điền `chưa làm` hết. Bạn sẽ cập nhật dần qua M1–M6. **Đây chính là thanh tiến độ thật của đồ án** — hữu ích cho bạn hơn cả cho người chấm.

3. Viết `docs/design-issues.md`: ghi lại 6 vấn đề ở Phần 0, mỗi vấn đề theo mẫu **ADR** (*Architecture Decision Record*):

   - **Bối cảnh** — mâu thuẫn/thiếu sót là gì, ở mục nào của doc
   - **Các lựa chọn** — ít nhất hai phương án
   - **Quyết định** — chọn cái nào
   - **Lý do** — tại sao, đánh đổi gì
   - **Hệ quả** — phải sửa gì trong doc/diagram

   ADR là một trong những thứ giá trị nhất bạn có thể học ở môn này. Sáu tháng sau, khi bạn quên vì sao mình chọn SQLite thay vì Postgres, ADR trả lời. Trong công ty thật, ADR là thứ cứu team khỏi tranh cãi lặp lại vô tận.

**Tự kiểm chứng:** đưa `docs/` cho một người bạn chưa biết gì về đồ án. Họ đọc xong có hiểu hệ thống làm gì và đang ở đâu không?

---

### ☐ M0-10 · `.gitignore` và `.env.example`

**Phần `.gitignore`:** ngay bây giờ repo đang có `demo/__pycache__/` được commit vào git — đó là file biên dịch, không bao giờ nên nằm trong version control.

Cần loại trừ: `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `*.db`, và **`.env`**.

Với `demo/__pycache__` đã lỡ commit: thêm vào `.gitignore` là chưa đủ, Git vẫn theo dõi file đã track. Bạn cần `git rm -r --cached` cho nó. Đây là một điểm mà rất nhiều người vấp — tra cứu để hiểu vì sao.

**Phần `.env.example`:** một file liệt kê **tên** các biến môi trường mà không có **giá trị**. Nó trả lời câu hỏi "muốn chạy dự án này thì cần cấu hình gì" mà không làm lộ secret nào.

Các biến bạn sẽ cần: khóa API Anthropic, token GitHub, webhook secret, đường dẫn database, tên model, và giới hạn token cho trimmer.

**Nguyên tắc nền tảng — 12-Factor App, factor III:** cấu hình phải nằm trong môi trường, không nằm trong code. Lý do: cùng một artifact code phải chạy được ở dev, staging, production mà không sửa một dòng nào.

**Nhắc lại một việc gấp:** `demo/RUN.txt` ghi rằng có một API key đã bị dán vào chat và bị lộ. Nếu bạn chưa revoke, làm ngay bây giờ tại console.anthropic.com. Một key bị lộ trên internet thường bị quét và dùng trong vòng vài giờ.

**Tự kiểm chứng:** `git status` sạch sau khi tạo venv và chạy test — nghĩa là mọi file rác đã bị ignore đúng.

---

## Phần 3 — Định nghĩa Hoàn thành cho M0

M0 xong khi **tất cả** những điều sau đúng:

- [ ] `git status` sạch ngay sau khi clone mới, cài đặt, và chạy test
- [ ] `pip install -e ".[dev]"` chạy được trên máy sạch (thử bằng cách xóa `.venv` và làm lại)
- [ ] `ruff check .` sạch
- [ ] `mypy src` sạch
- [ ] `pytest` → 1 passed
- [ ] CI xanh trên một Pull Request
- [ ] `main` được bảo vệ, không push trực tiếp được
- [ ] `docs/` có design document, `traceability.md`, và `design-issues.md` với 6 ADR
- [ ] Repo `ci-triage-sandbox` tồn tại, có 1 workflow fail và 1 PR đang mở
- [ ] API key cũ đã revoke

Không có tính năng nào được viết ở M0. Đúng như vậy.

---

## Phần 4 — Những khái niệm bạn vừa học

Đây là phần bạn nên đọc lại sau khi làm xong, không phải trước.

| Khái niệm | Ý nghĩa | Bạn gặp nó ở đâu trong M0 |
|---|---|---|
| **Shift-left** | Đẩy việc phát hiện lỗi về sớm nhất có thể trong vòng đời | Toàn bộ M0 |
| **Walking skeleton** | Dựng một đường mỏng xuyên suốt hệ thống trước, rồi làm dày | M0-7 |
| **Reproducible build** | Cùng input phải cho cùng output trên mọi máy | M0-1, M0-3, M0-5, M0-8 |
| **YAGNI** | Đừng xây thứ chưa cần | M0-3 |
| **Separation of concerns** | Runtime deps ≠ dev deps | M0-4 |
| **12-Factor / config in environment** | Cấu hình ở môi trường, không ở code | M0-10 |
| **Traceability** | Mọi dòng code truy ngược được về một yêu cầu | M0-9 |
| **ADR** | Ghi lại quyết định kiến trúc kèm lý do | M0-9 |
| **Signal-to-noise trong VCS** | Diff phải phản ánh thay đổi thật | M0-1 |

---

## Bắt đầu từ đâu

Làm M0-1 trước (5 phút, gỡ được 29 file nhiễu), rồi M0-10 phần revoke key (2 phút, rủi ro thật). Xong hai cái đó hãy đi tuần tự.

Khi kẹt ở task nào, hỏi tôi **câu hỏi cụ thể** — "ruff báo lỗi E501 ở file X, tôi nên sửa hay nên đổi line-length?" tốt hơn nhiều so với "làm sao cấu hình ruff". Câu hỏi cụ thể là thứ bạn sẽ phải học cách đặt khi đi làm.

Khi xong M0, báo tôi kèm output của `pytest` và link CI run — tôi review rồi mình vào M1.
