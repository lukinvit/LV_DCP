# Privacy: секреты, PII, context filters

4 идеи, закрывают ТЗ §17 (privacy_mode).

---

## 1. gitleaks + detect-secrets гибрид

- **Что даёт:** два уровня проверки секретов перед отправкой pack в Claude API:
  - **gitleaks** (Go, subprocess) — полное сканирование на bootstrap проекта, baseline-файл для известных false-positives.
  - **detect-secrets** (Python, inline) — быстрая inline-проверка на hot-path каждого pack-запроса; entropy + regex, меньше false-positives.
- **Проблема:** прямая утечка API-ключа, JWT, DB-credentials в LLM-логи — блокер для production. ТЗ §17 обязателен.
- **Где:**
  - `libs/policies/privacy.py` — Python-проверка (detect-secrets).
  - `apps/agent/preflight.py` — запуск gitleaks на bootstrap.
  - `libs/policies/baseline.py` — baseline для known-leaks.
- **Влияние:** **H** — блокер production.
- **Срок:** **2–3 дня**.
- **Источники:** gitleaks/gitleaks (18k★), Yelp/detect-secrets (4k★).

---

## 2. Cody-style context filters (glob/regex запреты)

- **Что даёт:** `cody.contextFilters`-подобный формат: список glob/regex, которые **никогда** не уходят в LLM даже если попали в retrieval-результат. Пример: `secrets/*.yaml`, `**/*.env`, `apps/billing/**`.
- **Проблема:** regex на секретах ловит API-ключи, но целые конфиденциальные модули (биллинг, внутренние политики) надо вычитать glob-ом.
- **Где:** `libs/policies/context_filters.py`, конфиг `.contextfilters.yaml` в корне проекта или workspace.
- **Влияние:** **M-H** — комплементарно к секрет-сканеру.
- **Срок:** **1–2 дня**.
- **Источник:** Sourcegraph Cody `cody.contextFilters`.

---

## 3. Microsoft Presidio для PII redaction

- **Что даёт:** NER + patterns для детекции EMAIL/PHONE/CREDIT_CARD/IP-адресов в комментариях, docstrings, строках. Reversible pseudonymization — сохраняем mapping, LLM-ответ разворачиваем обратно.
- **Проблема:** секреты это API-ключи, но в коде бывают **PII-артефакты**: e-mail'ы в комментариях, IP-адреса в тестах, имена в логах. Их тоже не стоит отправлять в LLM.
- **Где:** `libs/policies/presidio.py`, опционально подключается через privacy_mode=strict.
- **Влияние:** **M** — для enterprise-сценариев критично.
- **Срок:** **3–5 дней**.
- **Источник:** microsoft/presidio (4k★).

---

## 4. pre-commit как post-edit gate

- **Что даёт:** после каждого edit-цикла автоматически запускается `pre-commit run`: ruff, mypy, pytest-fast, gitleaks-scan на staged-файлах. Единообразие локально и в CI.
- **Проблема:** CLAUDE.md требует «lint/typecheck/test» после каждого edit, но сейчас это ручные make-команды. pre-commit делает это детерминированным.
- **Где:** `.pre-commit-config.yaml` в корне; `libs/impact/post_edit_gate.py` триггерит запуск после apply.
- **Влияние:** **M**.
- **Срок:** **0.5 дня**.
- **Источник:** pre-commit/pre-commit (14k★).

---

## Privacy modes (предлагаемая структура)

```yaml
# config/privacy.yaml
privacy_mode: strict  # off | redact | strict

strict:
  secrets:
    scanners: [detect-secrets, gitleaks]
    on_detect: block  # block | redact | warn
  pii:
    scanners: [presidio]
    entities: [EMAIL, PHONE, IP, CREDIT_CARD]
    on_detect: redact
  context_filters:
    path_globs: ["secrets/**", "apps/billing/**", ".env*"]

redact:
  secrets: {scanners: [detect-secrets], on_detect: redact}
  pii: {scanners: [presidio], on_detect: redact}

off:
  # только пользовательский .dcpignore
```

## Связанные, отложенные

- **trufflehog verified-mode** — проверяет, живой ли найденный ключ API-вызовом. Мощно, но добавляет latency и сетевой I/O в hot-path. Для фазы 3 как optional alert-mode.
- **Lunary RBAC** — для многопользовательского workspace фазы 3.

## Чеклист готовности

- [ ] `make privacy-scan /path/to/repo` возвращает findings в JSON.
- [ ] Pack-endpoint падает с `PrivacyViolation` если найден live-секрет.
- [ ] PII redaction reversible (ответ Claude можно развернуть обратно).
- [ ] Baseline-файл коммитится в репо, CI проверяет что новых leak нет.
- [ ] `privacy_mode=strict` проходит e2e-тест на модельном репо с заложенными «ловушками».
