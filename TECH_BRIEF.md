# CI Failure Triage Bot — Tech Brief trước giai đoạn code

*Người viết: tech lead review. Ngày: 2026-08-18. Nguồn: đọc toàn bộ repo `ci-triage-bot` @ `a492ead`.*

---

## 1. Đồ án này thực chất là gì

**Mục tiêu cuối:** một GitHub App/webhook bot. Khi một workflow run **fail**, bot tải log của run đó, cắt gọn, gửi cho Claude với schema bắt buộc (forced tool use), validate kết quả, rồi post một comment triage (category / confidence / root cause / suggested fix) lên PR tương ứng.

**Môn học:** Nhập môn Công nghệ phần mềm, ticket `NMCNPM-*`. Team: Trần Gia Huy (lead), Nguyễn Hoàng Danh, Vũ Mạnh Quân.

**Điểm quan trọng nhất cần hiểu:** đồ án được chấm theo **tài liệu thiết kế**, không chỉ theo code chạy được. Code trong repo hiện tại refer tới các mục "3.3.7 / 3.3.9 / 4.2 / 5.2.5" của một design document **không có trong repo**. Đây là rủi ro traceability — xem §7.

---

## 2. Hiện trạng thực tế (không phải hiện trạng theo diagram)

| Thành phần | Diagram nói | Code có |
|---|---|---|
| WebhookController | ✅ | ❌ — thay bằng dict hardcode trong `run()` |
| SignatureVerifier | ✅ | ✅ (HMAC-SHA256, `compare_digest`) |
| EventFilter | ✅ | ✅ (3 điều kiện) |
| **TriageService** (orchestrator) | ✅ | ❌ — orchestration nằm procedural trong hàm `run(args)` |
| GitHubClient | 3 method | chỉ có `post_pr_comment()`; **`get_workflow_logs()` chưa tồn tại** |
| ClaudeClient | ✅ | ✅ (forced `tool_choice`) |
| LogTrimmer | ✅ | ✅ (tail 40 + 10 regex ± 3 context, cap 60) |
| PromptBuilder | ✅ | ✅ |
| ResponseValidator | ✅ | ✅ (6 rule) |
| MarkdownFormatter | ✅ | ✅ |
| TriageResult (DTO) | 11 field | ✅ nhưng thiếu `id`, `repository_id` |
| WebhookPayload (DTO) | ✅ | ✅ |
| ConfigManager | ✅ | ❌ |
| HistoryStore | ✅ | ❌ |
| RepoManager | ✅ | ❌ |
| RepositoryConfig | ✅ | ❌ |
| DashboardController | ✅ | ❌ |
| DB (2 bảng Postgres/SQLite) | ✅ | ❌ |

**Tỉ lệ: 9/17 class tồn tại, tất cả nằm trong một file demo.** Không có HTTP server, không persistence, không config, **không một dòng test nào**, không CI, không packaging.

Ngoài ra `demo/triage_demo.py` trộn lẫn 2 thứ trong cùng file:
- ~230 dòng là **logic sản phẩm** (9 class pipeline)
- ~620 dòng là **logic trình chiếu** (ANSI box, `Step` timer, `--focus`, `build_big_log()` sinh log giả 12.000 dòng)

Đây là điều phải tách đầu tiên. Demo là tài sản quý (nó là thứ ăn 20% điểm "Example/demo"), nhưng nó **không được là** production source.

---

## 3. Những gì đã làm đúng — giữ nguyên, đừng viết lại

1. **Spike NMCNPM-43 là engineering thật.** So sánh prompt-only vs tool-based, 40 API call, có ground truth, có bảng kết quả. Quyết định `tool_choice={"type":"tool"}` có bằng chứng thực nghiệm chứ không phải cảm tính. Giữ nguyên `spike/`, **freeze** nó, đừng refactor.
2. **`hmac.compare_digest` thay vì `==`.** Đúng, và biết vì sao đúng.
3. **`ResponseValidator` tồn tại dù output đã schema-conformant by construction.** Lý do: `confidence_score` range và giới hạn 600 ký tự chỉ là *prose trong field `description`*, API **không** enforce (không có `minimum`/`maximum`/`maxLength` thật). Insight này là điểm sáng nhất của cả đồ án — giữ nguyên và nói lại trong báo cáo.
4. **Thuật toán LogTrimmer** (tail + regex + context) hợp lý về nguyên tắc — nhưng có bug ưu tiên, xem §4.
5. **`urllib` thuần, zero dependency ngoài `anthropic`** cho demo. Tốt cho demo. Sang production thì đổi sang `httpx` để có retry/timeout tử tế.

---

## 4. Bug & nợ kỹ thuật tôi tìm thấy khi đọc code

Xếp theo mức độ nguy hiểm.

### 🔴 P0 — `LogTrimmer` có thể vứt mất chính câu trả lời

```python
idx = sorted(keep)[-self.max_lines:]   # triage_demo.py:355
```

`keep` = (40 dòng cuối) ∪ (context quanh mọi error hit). Cắt bằng `[-60:]` nghĩa là **giữ 60 index LỚN NHẤT** → ưu tiên dòng ở cuối file, **không** ưu tiên dòng có lỗi.

Hệ quả: nếu lỗi xảy ra sớm (ví dụ `pip install` fail ở phút đầu, sau đó 12.000 dòng noise của step khác), và có > 20 hit rải rác, thì các hit sớm nhất — tức là **nguyên nhân gốc** — bị cắt, còn lại toàn noise ở cuối.

Lý do bug này chưa bao giờ lộ: `build_big_log()` luôn nhét khối lỗi vào **cuối** log. Cả 4 sample của spike cũng vậy.

**Fix:** đổi chiến lược ưu tiên — luôn giữ toàn bộ error hit + context trước, phần ngân sách còn lại mới dành cho tail. Và **bắt buộc** có test case "lỗi ở đầu log".

### 🔴 P0 — `get_workflow_logs()` chưa ai đụng vào, và nó khó hơn mọi người tưởng

GitHub REST `GET /repos/{o}/{r}/actions/runs/{id}/logs` **không trả text**. Nó trả `302` redirect tới một **file ZIP** chứa nhiều `.txt` (một file cho mỗi job, cộng thư mục per-step). Bạn phải: follow redirect (nhưng **không** kèm header `Authorization` sang domain storage), unzip trong memory, chọn đúng job đã fail, ghép log.

Đây là **rủi ro số 1** của cả phase code. Toàn bộ pipeline hiện tại đứng trên `build_big_log()` — một hàm sinh log giả. Chưa một byte log GitHub thật nào chạy qua `LogTrimmer`.

**Đề xuất:** làm cái này **sớm**, ngay milestone M2, không để cuối. Rất có thể log thật có định dạng khác đủ để phải chỉnh lại regex patterns.

### 🟠 P1 — Webhook không thể xử lý đồng bộ

GitHub yêu cầu webhook trả response nhanh (~10s). Pipeline hiện tại: tải ZIP log (có thể vài MB) + gọi Claude (~3s) + post comment. Sẽ timeout.

**Bắt buộc:** nhận webhook → verify chữ ký → trả `202 Accepted` ngay → xử lý nền. Đây là **quyết định kiến trúc phải chốt trước khi gõ code** (xem §8).

### 🟠 P1 — Không có idempotency → comment trùng

GitHub retry webhook khi không nhận được 2xx. Không có gì chặn bot post 2–3 comment giống hệt nhau lên cùng một PR.

**Fix:** `UNIQUE(repository_id, run_id)` trong bảng `triage_result` (data diagram hiện **chưa có** constraint này — cần bổ sung vào tài liệu), và check trước khi gọi Claude (tiết kiệm cả tiền API).

### 🟠 P1 — `pull_requests` rỗng với PR từ fork

`workflow_run.pull_requests` là mảng **rỗng** khi PR đến từ fork repo — cạm bẫy GitHub kinh điển. Code hiện tại: `prs = wr.get("pull_requests") or [{}]` → `pr_number = None` → step 9 sẽ post vào `/issues/None/comments`.

**Fix:** fallback resolve PR qua `GET /repos/{o}/{r}/commits/{head_sha}/pulls`, và nếu vẫn không có thì skip có log rõ ràng.

### 🟡 P2 — Schema bị duplicate ở 2 nơi

`spike/triage_schema.json` và `SCHEMA` dict trong `triage_demo.py`. CLAUDE.md tự thừa nhận "must be kept in sync" — đó là code smell, không phải feature. **Single source of truth:** một `schema.py` (hoặc load từ JSON), mọi nơi khác import.

### 🟡 P2 — Secret hardcode trong source

`WEBHOOK_SECRET = b"demo-shared-secret-not-a-real-one"` (dòng 47). Chấp nhận được cho demo, không chấp nhận được khi có server thật. Ngoài ra `RUN.txt` ghi rõ có một API key đã bị lộ trong chat — **kiểm tra lại đã revoke chưa**.

### 🟡 P2 — Biến môi trường đặt tên sai ngữ cảnh

`MODEL = os.environ.get("SPIKE_MODEL", ...)` trong file `demo/` — kế thừa từ spike. Đổi thành `TRIAGE_MODEL` / đưa vào ConfigManager.

### 🟢 P3 — Toàn bộ 29 file đang "modified" trong git

`git status` báo mọi file đều sửa, `git diff` cho thấy 77 insert / 77 delete trên file 78 dòng → **CRLF vs LF**. Thêm `.gitattributes` với `* text=auto eol=lf` và `git add --renormalize .` trước khi làm bất cứ gì, nếu không mọi PR sau này sẽ là noise 100%.

---

## 5. Kiến trúc đề xuất cho giai đoạn code

Nguyên tắc: **tên module/class phải map 1-1 với class diagram**, vì đồ án chấm theo tài liệu. Không sáng tạo tên mới.

```
ci-triage-bot/
├── pyproject.toml
├── .gitattributes                # fix CRLF, làm ngay
├── .env.example
├── docs/                         # ⬅ THIẾU: đưa SRS/design doc vào đây
│   └── design.md
├── src/ci_triage/
│   ├── config.py                 # ConfigManager
│   ├── schema.py                 # ⬅ SINGLE SOURCE OF TRUTH của triage schema
│   ├── api/
│   │   ├── webhook.py            # WebhookController
│   │   └── dashboard.py          # DashboardController
│   ├── domain/
│   │   ├── payload.py            # WebhookPayload (DTO)
│   │   ├── result.py             # TriageResult (DTO)
│   │   └── repo_config.py        # RepositoryConfig (DTO)
│   ├── security/verifier.py      # SignatureVerifier
│   ├── filters/event_filter.py   # EventFilter
│   ├── services/triage.py        # TriageService  ⬅ orchestrator THẬT
│   ├── processing/
│   │   ├── trimmer.py            # LogTrimmer
│   │   ├── prompt_builder.py     # PromptBuilder
│   │   ├── validator.py          # ResponseValidator
│   │   └── formatter.py          # MarkdownFormatter
│   ├── clients/
│   │   ├── github_client.py      # GitHubClient (3 method đầy đủ)
│   │   └── claude_client.py      # ClaudeClient
│   └── storage/
│       ├── db.py
│       ├── history_store.py      # HistoryStore
│       └── repo_manager.py       # RepoManager
├── tests/
│   ├── unit/                     # 1 file test / 1 class
│   ├── integration/              # webhook → comment, dùng mock HTTP
│   └── fixtures/
│       ├── logs/                 # log GitHub THẬT, gồm case "lỗi ở đầu file"
│       └── payloads/             # webhook payload thật, gồm case fork PR
├── demo/                         # GIỮ. Sửa để import từ src/ci_triage
├── spike/                        # FREEZE. Không sửa.
└── diagrams/
```

**Stack đề xuất** (cân bằng giữa "đủ nghiêm túc để chấm" và "làm kịp deadline"):

| Hạng mục | Chọn | Vì sao |
|---|---|---|
| Web | FastAPI + uvicorn | async sẵn, `BackgroundTasks` sẵn, OpenAPI docs miễn phí (ăn điểm tài liệu) |
| Validation | Pydantic v2 | DTO trong diagram map thẳng sang model, `from_dict()`/`to_dict()` có sẵn |
| Config | pydantic-settings | = ConfigManager, đọc `.env`, không hardcode secret |
| DB | SQLAlchemy 2.0 + SQLite | đúng như data diagram ghi ("SQLite dev, Postgres-compatible") |
| HTTP | httpx | retry/timeout/redirect tử tế — cần cho vụ ZIP log |
| LLM | anthropic | giữ nguyên |
| Test | pytest + respx | respx mock httpx → test không tốn tiền API |
| Chất lượng | ruff + mypy | 2 công cụ, cấu hình 10 dòng |
| CI | GitHub Actions | tự nó là một CI để bot triage 😀 dùng làm demo luôn |

**Lưu ý kỹ thuật quan trọng khi lên FastAPI:** phải verify HMAC trên **raw body bytes** (`await request.body()`), *trước* khi parse JSON. Nếu để FastAPI parse rồi re-serialize để tính chữ ký, chữ ký sẽ luôn sai (khác whitespace/thứ tự key).

---

## 6. Kế hoạch milestone

Ước tính theo "ngày công của 1 người", 3 người có thể chạy song song M2/M4.

### M0 — Nền móng · 0.5 ngày · làm trước tiên, không thương lượng
- `.gitattributes` + `git add --renormalize .` (dọn 29 file noise)
- `pyproject.toml`, layout `src/`, `.env.example`
- ruff + mypy + pytest cấu hình
- GitHub Actions: lint + test chạy trên mọi push
- **DoD:** CI xanh trên một PR rỗng.

### M1 — Bóc domain ra khỏi demo · 1 ngày
- Chuyển 9 class từ `triage_demo.py` sang `src/ci_triage/`, giữ nguyên tên
- `schema.py` thành single source; `spike/triage_schema.json` giữ nguyên để lịch sử spike còn nguyên vẹn
- `demo/triage_demo.py` **import lại từ `src`** — demo vẫn chạy y hệt (đây chính là bằng chứng không regression)
- Unit test: SignatureVerifier, EventFilter, LogTrimmer, ResponseValidator, MarkdownFormatter, PromptBuilder
- **Fix P0 LogTrimmer** + test case "lỗi ở đầu log"
- **DoD:** `pytest` xanh, coverage ≥ 80% trên `processing/` + `security/`; `py demo/triage_demo.py --offline` cho output giống hệt trước.

### M2 — GitHub thật · 1.5 ngày · rủi ro cao nhất, làm sớm
- `get_workflow_logs()`: redirect → ZIP → chọn job failed → ghép text
- `get_run_details()`
- Resolve PR từ `head_sha` khi `pull_requests` rỗng
- Retry + rate-limit + timeout
- **DoD:** tải được log thật từ một repo demo có CI cố tình fail; log thật đó thành fixture trong `tests/fixtures/logs/`; `LogTrimmer` chạy trên nó vẫn giữ được dòng lỗi.

### M3 — Webhook service · 1 ngày
- FastAPI app, `POST /webhook`, verify trên raw bytes, trả `202` ngay
- Xử lý nền (xem quyết định §8)
- `GET /healthz`
- `TriageService.process_failed_run()` thành orchestrator thật (thay hàm `run()`)
- **DoD:** integration test: payload chữ ký hợp lệ → có comment; chữ ký sai → 401 và **không** gọi Claude.

### M4 — Persistence + idempotency · 1 ngày
- SQLAlchemy model khớp `data_diagram.svg`, **thêm** `UNIQUE(repository_id, run_id)`
- `HistoryStore`, `RepoManager`, `RepositoryConfig`
- Check trùng **trước** khi gọi Claude
- **DoD:** gửi cùng một webhook 2 lần → 1 comment, 1 row, 0 API call lần thứ hai.

### M5 — Dashboard · 0.5–1 ngày · cắt được nếu thiếu thời gian
- `GET /runs`, `GET /runs/{id}`, template Jinja2 tối giản
- **DoD:** xem được lịch sử triage trên trình duyệt.

### M6 — Hoàn thiện · 1 ngày
- Structured logging, error handling thống nhất, README, `docker-compose.yml` hoặc hướng dẫn ngrok cho demo live
- Chạy lại spike trên eval set để có số liệu mới cho báo cáo
- **DoD:** người ngoài clone repo, đọc README, chạy được trong 10 phút.

**Tổng: ~6–7 ngày công.** Đường găng là M2 → M3 → M4.

---

## 7. Traceability — việc bị bỏ quên nhưng ăn điểm nặng

Code refer tới "section 3.3.7 / 3.3.9 / 4.2 / 5.2.5" nhưng **repo không có tài liệu đó**. Bốn SVG là "the closest thing to a design doc" (nguyên văn CLAUDE.md).

Nên làm ngay trong M0:
1. Đưa SRS/design document (bản `.docx`/`.pdf` nộp cho môn) vào `docs/`.
2. Viết một bảng **traceability matrix** `docs/traceability.md`: mỗi class trong diagram → module trong `src/` → file test. Người chấm sẽ tìm đúng cái này.
3. Cập nhật `data_diagram.svg` với `UNIQUE(repository_id, run_id)` — tài liệu phải khớp code, không phải ngược lại.
4. Cập nhật diagram/tài liệu để phản ánh việc xử lý bất đồng bộ (nếu chốt phương án queue/background).

---

## 8. Ba quyết định phải chốt trước khi gõ dòng code đầu tiên

1. **Xử lý bất đồng bộ bằng gì?** FastAPI `BackgroundTasks` (đơn giản, mất job nếu process chết) vs Redis + RQ/Celery (đúng bài, thêm hạ tầng) vs bảng job trong SQLite + worker thread (không thêm dependency, tự viết retry).
2. **Có làm Dashboard không?** Nó là 2 class trong diagram (`DashboardController`, `HistoryStore`) — bỏ thì lệch tài liệu, làm thì tốn ~1 ngày.
3. **Refactor demo hay giữ song song?** Bóc domain ra `src/` rồi cho demo import lại (sạch, nhưng đụng vào thứ đang chạy được trước buổi bảo vệ) vs để demo nguyên vẹn và viết `src/` mới (an toàn, nhưng lại duplicate logic — đúng cái smell ta vừa chê).

Khuyến nghị của tôi: **(1)** bảng job trong SQLite + worker thread — không thêm hạ tầng, vẫn nói được "durable, retryable" trong báo cáo; **(2)** làm, nhưng để M5 và cắt được; **(3)** bóc ra `src/` **nhưng chỉ sau khi buổi seminar đã xong** — nếu seminar chưa diễn ra thì đóng băng `demo/` cho tới lúc đó.

---

## 9. Definition of Done chung cho mọi ticket từ giờ

- [ ] Code có type hint, `mypy` sạch
- [ ] `ruff` sạch
- [ ] Có unit test cho happy path **và** ít nhất 1 edge case
- [ ] Không gọi API thật trong test (mock bằng respx)
- [ ] Không có secret trong source
- [ ] Tên class/method khớp class diagram, hoặc diagram được cập nhật kèm trong cùng PR
- [ ] CI xanh

---

## 10. Ba việc làm ngay hôm nay

1. `.gitattributes` + `git add --renormalize .` — 5 phút, tránh 29 file noise vĩnh viễn.
2. Kiểm tra API key bị lộ ghi trong `demo/RUN.txt` đã revoke chưa — 2 phút.
3. Tạo một repo demo trên GitHub với CI cố tình fail, tải thử một file ZIP log thật về xem nó trông thế nào — 30 phút, và nó sẽ định hình toàn bộ M2.
