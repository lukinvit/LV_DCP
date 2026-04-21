# Desktop agent: watcher, sync, launchd

5 идей для `apps/agent/` — ядра Phase 1.

---

## 1. `watchfiles` вместо `watchdog`

- **Что даёт:** Rust-backend (notify-rs), async-first (`async for changes in awatch(...)`), встроенный debounce (`step=50ms`), batch-события как атомарный `set`. Rust-скорость на monorepos 10k+ файлов.
- **Проблема:**
  - watchdog теряет события после sleep/resume на macOS.
  - Деградирует на больших проектах (Python GIL на callback'ах).
  - Требует самописной debounce-очереди — у нас это ~200 строк lifecycle-кода.
- **Где:** `apps/agent/watcher.py` (полная замена).
- **Влияние:** **H** — убирает целый класс багов watcher'а.
- **Срок:** **2–3 дня** (миграция + регресс-тесты).
- **Источник:** samuelcolvin/watchfiles (2k★).

---

## 2. Merkle-tree sync между агентом и backend

- **Что даёт:** клиент считает Merkle-хэш дерева файлов, сервер возвращает diff-ноды. Инкрементальный sync без пересылки всего состояния.
- **Проблема:** сейчас sync агент→backend идёт file-by-file по content-hash. При offline >1ч и последующем reconnect — неэффективный reconciliation. Merkle-tree делает sync O(log n) по изменениям.
- **Где:** `apps/agent/sync.py`, `apps/backend/routes/sync.py`, новая таблица `merkle_nodes`.
- **Влияние:** **M-H** — робастность и скорость sync после долгого offline.
- **Срок:** **3–5 дней**.
- **Источник:** Cursor blog (sync protocol), Syncthing block-exchange.

---

## 3. Block-level hashing (rolling hash по 128KB блокам)

- **Что даёт:** вместо хэша всего файла — rolling hash блоков. При изменении одной функции в большом файле пересчитываем только затронутый блок, re-embed только его. Экономия LLM-бюджета на embed.
- **Проблема:** при изменении 10 строк в файле на 2000 строк сейчас мы пересчитываем embedding для всего файла. На среднем проекте это **20–50× лишних embed-вызовов**.
- **Где:** `apps/agent/hashing.py`, `libs/core/content.py`, `libs/embeddings/pipeline.py`.
- **Влияние:** **H** — фундаментально меняет cost-profile.
- **Срок:** **1–2 недели** (требует пересмотра payload schema и invalidation).
- **Источник:** Syncthing block-exchange protocol, rsync.

---

## 4. `.dcpignore` в формате `.stignore`

- **Что даёт:** `.gitignore`-синтаксис с расширениями: `!negate`, `(?i)` case-insensitive, `**/pattern`. Встроенные дефолты: `node_modules`, `dist`, `*.min.js`, `__pycache__`, `.venv`. Per-repo overrides.
- **Проблема:** пользователи уже знают `.gitignore`/`.stignore`, не надо учить новый формат. Сейчас exclusion-паттерны размазаны по `libs/policies/scan`.
- **Где:** `libs/policies/ignore.py`, корень каждого indexed проекта.
- **Влияние:** **M** (UX + предсказуемость).
- **Срок:** **2 часа**.
- **Источник:** Syncthing `.stignore`, Continue.dev `.continueignore`.

---

## 5. launchd best-practice plist

- **Что даёт:** production-ready plist:
  - `KeepAlive.Crashed=true` + `ThrottleInterval=30` — restart после crash с anti-flap.
  - `LimitLoadToSessionType=Aqua` — не запускать на loginwindow.
  - `LSUIElement=true` в Info.plist — без Dock-icon.
  - Health-probe после `WakeFromSleep` — пересоздать FSEvents stream.
  - Log rotation через `StandardOutPath` + `newsyslog.d`.
- **Проблема:** стабильность daemon на macOS — известная боль. Без этого списка агент «исчезает» после suspend/sleep.
- **Где:** `deploy/launchd/com.lvdcp.agent.plist`, `apps/agent/healthcheck.py`.
- **Влияние:** **M-H** — эксплуатационная стабильность.
- **Срок:** **1 день**.
- **Источник:** KeepingYouAwake, Mos, Hammerspoon — примеры production-launchd.

---

## Связанные, но отложенные

- **Syncthing vector clocks** для agent↔backend версионирования — 1–2 недели, overkill до фазы 3.
- **rclone bisync** как reconciliation pattern — подсмотреть алгоритм, не тащить бинарь.
- **Hammerspoon `hs.pathwatcher`** — альтернатива Python-watchdog, но только Lua. Не подходит архитектурно.
- **fswatch** — C++ CLI, только как референс для monitor-type abstraction.

## Проверочный чеклист после фазы 1

- [ ] Watcher не теряет события после `sudo pmset sleepnow && wake`.
- [ ] Агент переживает `killall -9` и сам поднимается через 30 секунд (ThrottleInterval).
- [ ] Sync догоняет изменения за 15 минут offline быстрее, чем за 10 секунд после reconnect.
- [ ] Block-hash даёт re-embed <10% файла при точечной правке функции.
- [ ] `.dcpignore` в корне проекта читается без рестарта (hot-reload).
