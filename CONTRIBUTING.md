# Contributing — CI Failure Triage Bot

Áp dụng cho repo `ci-triage-bot` (đồ án môn Nhập môn Công nghệ phần mềm, HCMUS, ticket `NMCNPM-*`).

## Phạm vi các thư mục

| Thư mục | Trạng thái |
|---|---|
| `src/ci_triage/` | Đang phát triển tích cực — mọi PR tính năng nằm ở đây |
| `demo/` | **ĐÓNG BĂNG** cho tới sau buổi seminar/bảo vệ. Không sửa trừ khi ticket ghi rõ lý do |
| `spike/` | **ĐÓNG BĂNG vĩnh viễn** — tài liệu lịch sử của NMCNPM-43, không refactor |
| `docs/` | Cập nhật song song với code — mỗi PR hiện thực một class phải cập nhật `docs/traceability.md` |
| `diagrams/`, PDF thiết kế gốc | Không sửa — đã nộp cho môn học |

## Quy ước nhánh

- Không commit trực tiếp lên `main`. `main` được branch protection chặn push thẳng.
- Mỗi ticket = một nhánh, đặt tên: `<type>/NMCNPM-<số>-<mô-tả-ngắn>`
  Ví dụ: `feat/NMCNPM-51-log-trimmer`, `fix/NMCNPM-58-webhook-signature`

## Quy ước commit — Conventional Commits

```
<type>(<scope>): <mô tả ngắn, thì hiện tại, không viết hoa đầu, không dấu chấm cuối>
```

**`type`:**
- `feat` — tính năng mới
- `fix` — sửa lỗi
- `chore` — việc lặt vặt, không ảnh hưởng logic (deps, config)
- `docs` — chỉ đổi tài liệu
- `test` — thêm/sửa test
- `refactor` — sửa code không đổi hành vi
- `ci` — đổi pipeline

**`scope` gợi ý** (theo class/module trong class diagram — dùng lại tên đã có, đừng tự đặt tên khác):
`webhook`, `signature`, `event-filter`, `triage-service`, `github-client`, `claude-client`, `trimmer`, `prompt-builder`, `validator`, `formatter`, `history-store`, `repo-manager`, `config`, `dashboard`, `worker`, `db`, `docs`, `ci`

**Ví dụ:**
- `feat(trimmer): keep error hits before tail when budget is exceeded`
- `fix(webhook): resolve pr_number via head_sha when pull_requests is empty`
- `docs(traceability): mark GitHubClient as implemented`

## Quy trình Pull Request

1. Tạo nhánh từ `main` theo quy ước ở trên.
2. Code + test. Không PR nào được merge nếu thiếu test cho happy path.
3. Chạy local trước khi push — cả ba lệnh phải sạch:
   ```
   ruff check .
   mypy src
   pytest
   ```
4. Mở PR vào `main`. Trong mô tả PR, ghi rõ ticket `NMCNPM-*` liên quan.
5. Nếu PR hiện thực một class có trong class diagram → cập nhật `docs/traceability.md` (đổi trạng thái, điền file test tương ứng).
6. Nếu PR đi lệch khỏi design document gốc (thêm class không có trong diagram, đổi field DTO, đổi hành vi đã đặc tả) → thêm một ADR vào `docs/design-issues.md` trong **cùng PR đó**, không tách riêng.
7. CI phải xanh trước khi merge.

## Definition of Done cho mọi PR

- [ ] `ruff check .` sạch
- [ ] `mypy src` sạch
- [ ] `pytest` xanh, có test cho ít nhất 1 edge case (không chỉ happy path)
- [ ] Không gọi API thật trong test (mock bằng `respx` hoặc fixture)
- [ ] Không có secret trong source hoặc test fixture
- [ ] Tên class/method khớp class diagram, hoặc có ADR giải thích lý do khác biệt
- [ ] `docs/traceability.md` cập nhật nếu liên quan
- [ ] CI xanh

## Không được làm

- Không `git push --force` lên `main`.
- Không commit với `--no-verify`.
- Không commit file `.env` hay bất kỳ giá trị secret thật nào — chỉ `.env.example` với tên biến, không có giá trị.
- Không sửa `demo/` hoặc `spike/` ngoài phạm vi đã nêu ở trên.
