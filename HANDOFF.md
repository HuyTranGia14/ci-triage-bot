# HANDOFF — trạng thái đồ án & việc tiếp theo

*Đọc file này đầu tiên khi mở lại đồ án, dù trên máy nào hay dùng phiên làm việc Claude mới. Cập nhật file này vào cuối mỗi buổi làm việc quan trọng — đây là thói quen "engineering log" nên giữ suốt đồ án, không chỉ cho M0.*

Cập nhật lần cuối: 2026-08-18, cuối buổi làm việc đầu tiên (đang giữa M0).

---

## 1. Đồ án là gì (tóm tắt — chi tiết xem `TECH_BRIEF.md`)

CI Failure Triage Bot: bot GitHub webhook, khi một CI run fail thì tải log, cắt gọn, gửi Claude với schema bắt buộc (tool-based), validate, post comment triage lên PR. Đồ án môn Nhập môn CNPM (HCMUS, ticket `NMCNPM-*`). Repo: `github.com/HuyTranGia14/ci-triage-bot`.

**Trạng thái đầu buổi:** chỉ có demo/spike, không server, không DB, không test, không CI — 9/17 class trong design doc tồn tại, tất cả nhét trong `demo/triage_demo.py`.

**Design document đầy đủ** (42 trang PDF, Conceptual Model / Architectural Design / Data Design / UI Design) đã có, người dùng tự lưu — cần copy vào `docs/` (xem mục 5, việc chưa làm).

---

## 2. Ba quyết định kiến trúc đã chốt

1. **`demo/triage_demo.py` và toàn bộ `spike/` ĐÓNG BĂNG.** Lý do: seminar/bảo vệ chưa diễn ra, demo đang chạy tốt và ăn điểm "Example/demo" — không risk nó. Code mới viết song song trong `src/ci_triage/`, hợp nhất sau seminar.
2. **Xử lý bất đồng bộ cho webhook = bảng job trong SQLite + worker thread** (không dùng Celery/Redis, không dùng FastAPI `BackgroundTasks`). Lý do: không thêm hạ tầng ngoài, vẫn nói được "durable + retryable" khi bảo vệ.
3. **Scope code = M0–M6 đầy đủ**, gồm cả Dashboard, khớp 17 class trong diagram + phần bổ sung ở mục 3. Ước tính ~7 ngày công, đường găng M2 (GitHub thật) → M3 (webhook) → M4 (idempotency).

Stack đã chốt: FastAPI + Pydantic v2 + pydantic-settings + SQLAlchemy 2.0 + SQLite (dev) + httpx + anthropic SDK + pytest/respx/ruff/mypy.

---

## 3. Sáu vấn đề tìm thấy khi đọc design doc — quyết định cuối

**Không sửa file PDF** (đã nộp cho môn học). Mọi quyết định dưới đây chỉ áp dụng khi viết code trong `src/ci_triage/`. Ghi lại ở đây để không quên; bản ADR đầy đủ (giải thích chi tiết, theo mẫu Bối cảnh/Lựa chọn/Quyết định/Lý do/Hệ quả) vẫn là việc user tự viết vào `docs/design-issues.md` — xem mục 5.

| # | Vấn đề | Quyết định |
|---|---|---|
| 1 | Màn Triage Detail (5.2.2) cần trimmed log/prompt/raw response/raw webhook JSON, nhưng bảng `triage_result` (4.1) không có cột nào chứa | Tách bảng phụ **`triage_artifact`** (1:1 với `triage_result`): `trimmed_log`, `prompt_sent`, `raw_response`, `raw_webhook_json`. Lazy-load, không join vào `list_recent()` để không làm nặng query danh sách |
| 2 | `SignatureVerifier.shared_secret` là 1 secret (3.2.2) nhưng `RepoManager.find_by_repo` ngụ ý secret theo repo (3.2.14) | **Per-repo secret.** Bằng chứng mạnh nhất: màn Connect Repository (5.2.3) có ô "Webhook secret (Auto-generated)" theo từng repo. Giải quyết chicken-and-egg an toàn: đọc `repository.full_name` từ JSON thô (chưa tin cậy) chỉ để tra `RepoManager.find_by_repo()` → lấy `webhook_secret_ref` → resolve secret thật → verify HMAC trên **raw body bytes** với secret đó (`hmac.compare_digest`). Quyết định chấp nhận/từ chối request không bao giờ dựa vào tên repo tự khai, chỉ dựa vào kết quả verify. Không khớp repo nào → 401 chung chung, không tiết lộ lý do |
| 3 | 3.2.8/3.2.9 mô tả theo prompt-only, mâu thuẫn với 4.2 đã chốt tool-based | **Tool-based** — khớp sẵn 4.2 và spike đã chạy. `ClaudeClient.complete()` trả `dict` đã parse, `ResponseValidator.validate()` nhận `dict` thẳng, không có bước extract JSON từ text |
| 4 | DTO `WebhookPayload` (3.2.16) chỉ có 4 field, thiếu field pipeline cần | Bổ sung khi code: `conclusion: str`, `pr_number: int \| None`, `head_sha: str` |
| 5 | `triage_result` (4.1) thiếu ràng buộc UNIQUE dù 3.2.13 yêu cầu `save()` idempotent | Thêm `UNIQUE(repository_id, run_id)` vào SQLAlchemy model khi tạo bảng |
| 6 | Không class nào chịu trách nhiệm cơ chế background dispatch | Bổ sung khi code: bảng `triage_job` (status pending/processing/done/failed) + class `TriageWorker` (poll loop, atomic claim bằng `UPDATE ... WHERE status='pending'`). `WebhookController` sau `EventFilter` chỉ enqueue rồi trả `202` ngay, không gọi `TriageService` trực tiếp trong request handler |

Phụ: template Markdown comment lấy theo mục 5.2.5 của doc (không theo `demo/comment.md`); màn Settings không bao giờ lưu API key thật vào DB, chỉ đọc từ biến môi trường và hiển thị dạng che.

---

## 4. Bug đã tìm thấy trong code cũ (`demo/triage_demo.py`) — CHƯA fix, nhớ khi viết `src/ci_triage/`

- **P0** `LogTrimmer.trim()` dòng `sorted(keep)[-60:]` — ưu tiên nhầm 60 dòng **cuối file** thay vì 60 dòng gần lỗi nhất. Lỗi xảy ra sớm trong log có thể bị cắt mất. Chưa lộ vì log giả (`build_big_log()`) luôn nhét lỗi ở cuối. → phải viết test case "lỗi ở đầu log" khi làm lại `LogTrimmer` ở M1.
- **P0** `GitHubClient.get_workflow_logs()` chưa tồn tại. GitHub trả redirect → file ZIP nhiều `.txt`, không phải text thẳng. Rủi ro lớn nhất của cả dự án — làm sớm ở M2, đừng để cuối.
- **P1** `workflow_run.pull_requests` rỗng khi PR từ fork → `pr_number = None`. Cần fallback resolve qua `GET /repos/{o}/{r}/commits/{head_sha}/pulls`.
- **P2** Schema triage trùng lặp ở `spike/triage_schema.json` và `SCHEMA` dict trong `demo/triage_demo.py`. Khi viết `src/ci_triage/schema.py`, đây là nguồn duy nhất.
- **Cần xác nhận:** API key bị dán lộ trong `demo/RUN.txt` đã revoke chưa (console.anthropic.com → Billing/API Keys).

---

## 5. Trạng thái M0 — checklist chi tiết

Tham chiếu đầy đủ: `M0_GUIDE.md` (10 task, giải thích tại sao từng bước).

- [x] **M0-1 dọn CRLF/LF** — `.gitattributes` đã tạo, đã `git add --renormalize .`. **Lưu ý sự cố đã gặp:** repo thật nằm ở `C:\Users\PC\Desktop\ci-triage-bot\ci-triage-bot` (có `.git` với lịch sử commit `a492ead`/`08fb20b`); có một `.git` **rỗng** khác bị lỡ tạo ở thư mục cha `C:\Users\PC\Desktop\ci-triage-bot` — đã hướng dẫn xoá. **Luôn `cd` vào thư mục con `ci-triage-bot\ci-triage-bot` trước khi chạy git.** Chưa xác nhận lại `git status` sạch sau lần commit cuối — kiểm tra lại đầu buổi sau.
- [ ] **M0-2 quy ước nhánh/commit** — `CONTRIBUTING.md` đã viết (tailored, thay bản generic ban đầu). **Chưa làm:** bật branch protection cho `main` trên GitHub (Settings → Branches).
- [~] **M0-3 khung thư mục `src/`** — đã tạo, nhưng **lệch khỏi khuyến nghị YAGNI ban đầu**: toàn bộ 17 file class đã được scaffold rỗng sẵn (`api/`, `clients/`, `domain/`, `filters/`, `processing/`, `security/`, `services/`, `storage/`), kèm `config.py`, `schema.py` ở gốc. Đã flag việc này với user, **user chọn giữ nguyên** thay vì dọn về tối thiểu. Ghi nhận đây là quyết định có ý thức, không phải sai sót — nhưng hệ quả là mypy hiện chạy qua "20 source files" phần lớn rỗng. `src/ci_triage/__init__.py` đã có `__version__ = "0.1.0"`.
- [x] **M0-4 `pyproject.toml`** — hoàn chỉnh, đã verify: `pip install -e ".[dev]"` chạy được, `import ci_triage; print(__version__)` → `0.1.0`.
- [x] **M0-5 venv** — `.venv/` đã tạo và activate được.
- [x] **M0-6 ruff + mypy + pytest config** — nằm trong `pyproject.toml`. Verify: `ruff check .` → "All checks passed!"; `mypy src` → "Success: no issues found in 20 source files".
- [~] **M0-7 test đầu tiên** — đang làm dở. `tests/unit/test_version.py` đã viết, gặp lỗi `ModuleNotFoundError: No module named 'src'` do import sai `from src.ci_triage import __version__` thay vì `from ci_triage import __version__` (bài học src-layout: `src/` không phải package, chỉ là vị trí vật lý; tên import đúng là tên đã khai trong `pyproject.toml` → `packages = ["src/ci_triage"]`). **Đã sửa hướng dẫn, CHƯA xác nhận `pytest -v` chạy `1 passed`** — việc đầu tiên cần làm ở buổi tiếp theo.
- [ ] **M0-8 GitHub Actions CI** — chưa làm, chưa có `.github/workflows/ci.yml`. Cũng chưa tạo repo `ci-triage-sandbox` (repo phụ có CI cố tình fail + 1 PR mở, dùng làm nguồn log thật cho M2).
- [ ] **M0-9 `docs/traceability.md` + `docs/design-issues.md`** — chưa làm. `docs/design.md` đang 0 byte (cần copy nội dung/đính kèm PDF design doc gốc vào đây). Bảng quyết định ở mục 3 phía trên là input để viết 6 ADR vào `design-issues.md`.
- [ ] **M0-10 `.gitignore` + `.env.example`** — `.env.example` đang 0 byte, chưa điền tên biến. `.gitignore` chưa xác nhận có tồn tại — cần kiểm tra, và `demo/__pycache__` (nếu còn bị track) cần `git rm -r --cached`. **Chưa xác nhận API key cũ đã revoke.**

---

## 6. Việc cần làm ở buổi tiếp theo, theo thứ tự

1. Xác nhận `git status` sạch (M0-1 dư âm).
2. Sửa `tests/unit/test_version.py` (đổi `from src.ci_triage import` → `from ci_triage import`), chạy `pytest -v` → phải ra `1 passed`. Đây là việc dở dang gần nhất.
3. M0-10: viết `.gitignore` (`.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `*.db`, `.env`), điền `.env.example` (tên biến: khóa API Anthropic, GitHub token, webhook secret, đường dẫn DB, tên model, giới hạn token trimmer — không giá trị thật). Xác nhận đã revoke API key cũ bị lộ trong `demo/RUN.txt`.
4. M0-2 phần còn thiếu: bật branch protection cho `main` trên GitHub.
5. M0-8: viết `.github/workflows/ci.yml` (checkout → setup Python 3.11 → `pip install -e ".[dev]"` → ruff → mypy → pytest), mở PR thử để xem badge CI. Tạo repo GitHub riêng `ci-triage-sandbox` với 1 workflow cố tình fail + 1 PR đang mở (nguồn log thật cho M2 sau này).
6. M0-9: copy design doc PDF vào `docs/`, viết `docs/traceability.md` (bảng class diagram → module dự kiến → file test → trạng thái), viết `docs/design-issues.md` với 6 ADR dựa theo bảng ở mục 3 phía trên (Bối cảnh / Lựa chọn / Quyết định / Lý do / Hệ quả cho từng vấn đề).
7. Chạy lại toàn bộ Definition of Done của M0 (`M0_GUIDE.md` mục "Phần 3") để xác nhận M0 thật sự xong trước khi báo cáo và chuyển sang M1.
8. **M1** (chưa bắt đầu): bóc 9 class hiện có trong `demo/triage_demo.py` sang `src/ci_triage/`, giữ nguyên tên theo class diagram; `demo/triage_demo.py` sửa để import lại từ `src` (không đổi hành vi — chạy `--offline` phải ra output y hệt trước refactor); viết unit test cho `SignatureVerifier`, `EventFilter`, `LogTrimmer` (kèm fix bug P0 + test case "lỗi ở đầu log"), `ResponseValidator`, `MarkdownFormatter`, `PromptBuilder`.

---

## 7. Lưu ý môi trường (đừng quên khi đổi máy)

- Windows: **luôn dùng `py`**, không dùng `python` (trên máy hiện tại `python` trỏ vào MSYS2 hỏng — máy khác có thể khác, kiểm tra lại).
- Repo thật nằm **một cấp trong** thư mục `ci-triage-bot` bạn thấy trên Desktop: `...\ci-triage-bot\ci-triage-bot\`. Luôn `cd` vào đúng cấp đó trước khi chạy git/py.
- Kích hoạt venv trước khi cài/chạy bất cứ gì: `.\.venv\Scripts\Activate.ps1`. Nếu bị chặn bởi execution policy: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
- Cài đặt: `pip install -e ".[dev]"` (không phải `pip install -r requirements.txt` — dự án không dùng file đó).
- Trên máy mới: sau khi `git clone`, phải tự tạo lại `.venv/` — nó không nằm trong git (đúng, vì đã/`.gitignore` nên loại trừ).

---

## 8. Tài liệu tham khảo trong repo

- `TECH_BRIEF.md` — phân tích kiến trúc đầy đủ, kế hoạch M0–M6 chi tiết, lý do chọn stack.
- `M0_GUIDE.md` — hướng dẫn từng bước 10 task của M0, kèm giải thích khái niệm SE (shift-left, walking skeleton, YAGNI, 12-factor, ADR...).
- `CONTRIBUTING.md` — quy ước nhánh/commit/PR, Definition of Done cho mọi PR.
- Design document gốc (PDF 42 trang, chưa copy vào `docs/` — xem mục 6 việc số 6).

## 9. Nguyên tắc làm việc đã thống nhất (nhắc lại cho phiên Claude mới nếu dùng)

Mục tiêu người dùng là **học software engineering qua đồ án này**, không chỉ có code chạy. Vì vậy: không viết sẵn code nghiệp vụ (logic trong `src/ci_triage/`) — chỉ hướng dẫn từng bước kèm giải thích khái niệm và cách tự kiểm chứng. Ngoại lệ: file quy trình/tài liệu/cấu hình hạ tầng (`CONTRIBUTING.md`, `pyproject.toml`, CI yaml...) được viết trực tiếp khi người dùng yêu cầu rõ, vì đó không phải phần bài làm được chấm. Coi đồ án là làm một mình — không nhắc tên thành viên khác trong output.
