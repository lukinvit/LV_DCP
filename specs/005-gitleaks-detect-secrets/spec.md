# Feature Specification: gitleaks + detect-secrets Privacy Layer

**Feature Branch**: `005-gitleaks-detect-secrets`
**Created**: 2026-04-21
**Status**: Draft
**Input**: ideas-bank item #5 — перед отправкой любого pack в Claude API двухуровневая проверка секретов: gitleaks (subprocess) для полного сканирования репо на bootstrap, detect-secrets (inline-Python) для hot-path каждого запроса. Закрывает ТЗ §17 privacy-mode.

## User Scenarios & Testing

### User Story 1 — Блокировка pack с секретами в hot-path (Priority: P1)

Разработчик запускает `lvdcp_pack` по репо, где есть `.env.example` с `JWT_SECRET=abc123`. Inline detect-secrets сканирует контент перед отправкой в LLM; pack отклоняется с понятной ошибкой и маскированной подсказкой.

**Why this priority**: один из двух блокеров production-use (ТЗ §17); без этого LV_DCP нельзя включать на корпоративных репо.

**Independent Test**: `tests/integration/policies/test_privacy_inline.py` создаёт фикстуру с тремя типами секретов (AWS key, JWT, generic API token), ассертит что pack блокируется и возвращает `PrivacyViolation` с redacted positions.

**Acceptance Scenarios**:

1. **Given** файл с `AWS_SECRET_ACCESS_KEY=AKIA...`, **When** pack запрошен, **Then** возвращён 422 `PrivacyViolation`, структура ответа содержит `{file, line, kind}`, КОНКРЕТНЫЙ секрет никогда не попадает в ответ и в логи.
2. **Given** короткий допустимый токен (низкая энтропия, похож на идентификатор класса), **When** pack запрошен, **Then** allowlist правила пропускают, pack возвращён.

---

### User Story 2 — Full-repo scan при bootstrap проекта (Priority: P1)

При первом `ctx scan <path>` субпроцесс `gitleaks detect --no-banner --report-format json --report-path -` запускается; результаты складываются в `privacy_scan_results` таблицу. Файлы/строки из репорта маркируются как "known secrets" и исключаются из embedding pipeline.

**Why this priority**: без bootstrap-скана мы эмбеддим секреты в Qdrant, что противоречит privacy-mode.

**Independent Test**: `tests/integration/cli/test_scan_privacy.py` — репо с секретами → `ctx scan` → проверить, что эмбеддинги для файлов с секретами пропущены, запись в `privacy_scan_results` создана.

**Acceptance Scenarios**:

1. **Given** репо с 3 файлами содержащими секреты, **When** `ctx scan`, **Then** gitleaks найдено 3+ issues, соответствующие файлы исключены из embedding pipeline.
2. **Given** чистое репо, **When** `ctx scan`, **Then** gitleaks возвращает 0 issues < 5 с, pipeline не блокируется.

---

### User Story 3 — Configurable redaction policy (Priority: P2)

Пользователь может выбрать `privacy_mode ∈ {strict, mask, permissive}`:
- `strict` — блокировать pack полностью.
- `mask` — заменить секрет на `[REDACTED:kind]`, вернуть pack.
- `permissive` — warning в логе, pack идёт целиком (только для dev).

**Why this priority**: разные корпоративные политики требуют разного поведения.

**Independent Test**: юнит-тесты parametrized над 3 режимами с одним контентом; ассертят поведение.

**Acceptance Scenarios**:

1. **Given** `privacy_mode=mask`, **When** pack содержит `sk-live-...`, **Then** в ответе `[REDACTED:openai_key]`, метрика `privacy_redactions_total{mode=mask}` инкрементирована.

---

### Edge Cases

- False positive: строка `password = "example"` — detect-secrets allowlist; пользователь может расширить `.secretsignore`.
- Gitleaks недоступен (не установлен) — fallback на detect-secrets only, warning; `lvdcp_status` показывает degraded.
- Очень большой файл (>5 MB) — detect-secrets scan стримингово, не блокирует pack > 2 с.
- Бинарные файлы — пропускаются в detect-secrets, gitleaks сам умеет.
- JSON с embedded credentials — parsed и fields проверяются.

## Requirements

### Functional Requirements

- **FR-001**: Модуль `libs/policies/privacy.py` предоставляет `async scan_content(text: str, *, mode: PrivacyMode) -> PrivacyScanResult` с полями `{violations: list[Violation], masked_text: str | None}`.
- **FR-002**: `Violation` содержит `{kind, line, col_start, col_end, entropy}` — **БЕЗ** самого секрета.
- **FR-003**: Inline-сканер использует `detect_secrets.scan.scan_line()` в `asyncio.to_thread`; предзагружает baseline plugins.
- **FR-004**: Bootstrap scanner использует subprocess `gitleaks detect --source <path> --report-format json --no-banner`; результаты парсятся и складываются в таблицу `privacy_scan_results`.
- **FR-005**: `apps/agent/preflight.py` MUST вызывать `scan_content` перед отправкой pack-контента на backend.
- **FR-006**: `PrivacyMode` = Enum {`STRICT`, `MASK`, `PERMISSIVE`}; значение читается из `ProjectsConfig.privacy.mode`.
- **FR-007**: Allowlist в `.secretsignore` в корне проекта (формат gitleaks-совместимый); если нет — дефолтные allowlist-паттерны.
- **FR-008**: Метрики: `privacy_violations_total{kind, mode}`, `privacy_scan_duration_ms`, `privacy_redactions_total{kind}`.
- **FR-009**: Логирование — **никогда** не логировать секрет целиком; только kind + позиция + hash-id.

### Key Entities

- **PrivacyScanResult** — DTO `{violations, masked_text, elapsed_ms, tool}`.
- **Violation** — DTO без текста секрета.
- **privacy_scan_results (table)** — Postgres: `id UUID, project_id UUID FK, file_path text, kind text, line int, detected_at TIMESTAMPTZ, source ENUM{gitleaks,detect_secrets}`.
- **PrivacyMode** — enum.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Zero секретов попадает в Claude API на eval-suite из 5 "dirty" репозиториев (проверка через mock LLM, который ассертит clean content).
- **SC-002**: False-positive rate < 5% на "clean" репозиториях (eval).
- **SC-003**: Inline scan latency ≤ 50 мс на 100 KB pack.
- **SC-004**: Bootstrap gitleaks scan ≤ 60 с на 10k файлов.
- **SC-005**: При `privacy_mode=strict` и обнаруженном секрете — pack **никогда не отправляется**, регрессионный тест ассертит это на 100 запусков.

## Assumptions

- `gitleaks` CLI установлен в docker worker image (Alpine-compatible binary available).
- `detect-secrets>=1.4` доступен как pip dep.
- ТЗ §17 privacy-mode — конституционное требование.
- Postgres schema расширяется новой таблицей через Alembic.
- Маскирование не ломает code structure downstream (LLM получит валидный код с placeholders).

## Dependencies & Constraints

- Независимо от: #1–4, #6–9.
- Блокирует: production rollout LV_DCP — без privacy нельзя включать на customer data.
- Constitution: прямое требование ТЗ §17.
- ADR-003: проверка в агенте (single writer), backend тоже проверяет как defence-in-depth.
- Budget: каждый pack +50 мс inline; bootstrap редкий → amortize на long-running daemon.
