# Timeline Index Rollout Runbook

**Feature:** spec-010 — Symbol Timeline Index
**Config namespace:** `DaemonConfig.timeline` (see `libs/core/projects_config.py:TimelineConfig`)
**Store:** `~/.lvdcp/symbol_timeline.db` (SQLite WAL; override via `LVDCP_TIMELINE_DB`)
**Status:** Dev default = enabled; prod compose = enabled only after passing staging smoke-test.

This runbook covers flipping the feature on/off, what to check at each step,
and how to roll back safely. The flag is cheap to toggle because the sink is
built lazily at scan time — no daemon restart is required for future scans
to pick up a new value.

---

## 1. Flags & knobs

| Key                                          | Default   | Meaning                                                                                          |
|----------------------------------------------|-----------|--------------------------------------------------------------------------------------------------|
| `timeline.enabled`                           | `true`    | Master kill-switch. `false` → scanner skips sink registration entirely (zero overhead, SC-003).  |
| `timeline.enable_timeline_enrichment`        | `true`    | Gate for pack-level `## Timeline facts` section (≤ 3 KB budget, Layer 4).                        |
| `timeline.retention_days`                    | `null`    | `null` → keep everything. Integer N → prune events older than N days on every `append`.          |
| `timeline.privacy_mode`                      | `balanced`| `strict` / `balanced` / `off` — controls what payload lands in events (docstrings, commit msgs). |
| `timeline.rename_similarity_threshold`       | `0.85`    | 0.0–1.0; how similar two symbols must be for the differ to label them as a rename.               |
| `timeline.pack_enrichment_markers`           | see code  | Query substrings that trigger pack enrichment (e.g. `когда`, `when was`, `since v`).             |
| `timeline.tag_watcher_poll_seconds`          | `60`      | How often the daemon re-reads `git tag` for snapshot promotion.                                  |
| `timeline.sink_plugins`                      | `[]`      | Additional `pkg.module:ClassName` import paths (Obsidian, etc.).                                 |
| **Env overrides**                            |           |                                                                                                  |
| `LVDCP_TIMELINE_DB`                          | unset     | Absolute path override for the SQLite store. Used by tests and CI.                               |

### Where to set values

- **Per-user dev:** `~/.lvdcp/config.yaml`, section `timeline:`.
- **CI / smoke tests:** env vars or a throwaway config pointed at `tmp_path`.
- **Prod compose:** no dedicated compose service today — the timeline lives
  inside the desktop agent, not the backend container. Prod rollout means
  "operator updates their personal `~/.lvdcp/config.yaml` and re-scans".

---

## 2. Dev rollout (current state)

Dev machines default to `enabled: true`. Nothing to do. Validate with:

```bash
uv run ctx timeline status       # shows store path, event count, last scan
uv run ctx doctor                # "timeline store" check should be PASS or WARN (never FAIL)
```

Expected WARN cases (not blockers):

- **missing file** — project has never been scanned with timeline enabled. Run `ctx scan`.
- **stale** — last scan > 7 days old. Re-scan the project of interest.

FAIL cases need intervention:

- **unopenable** — the SQLite file is locked or corrupt. Inspect with
  `sqlite3 ~/.lvdcp/symbol_timeline.db '.schema'`; if recoverable, close
  other agents; otherwise move the file aside and let the next scan rebuild.
- **corrupt schema** — schema drift (likely from a pre-release build). Back
  up the file, delete it, re-scan.

---

## 3. Prod rollout (gated, phased)

Goal: before flipping `enabled: true` for a production operator (someone who
scans large real repos with millions of LOC), pass the three-step smoke test.

### Step 3.1 — Baseline perf sanity (operator's machine)

```bash
# Fresh scan with timeline OFF
cat >/tmp/timeline-off.yaml <<EOF
timeline:
  enabled: false
EOF
LVDCP_CONFIG=/tmp/timeline-off.yaml uv run ctx scan /path/to/real/project --mode full
# Note the wall-clock + .context/ size
```

```bash
# Same project, timeline ON
uv run ctx scan /path/to/real/project --mode full
# Wall-clock should be ≤ 110 % of baseline (SC-003).
```

If overhead > 10 %, do **not** enable in prod. File a bug with:

- Python version, macOS version
- Project size (file count, LOC)
- Timeline store size after scan
- `ctx timeline status` output
- `ctx doctor --json` output

### Step 3.2 — Pack footprint sanity

Goal: verify SC-001 — enriching a pack with timeline facts does not blow
the token budget beyond ~10 % of the base pack size.

```bash
# Before timeline
uv run ctx pack "когда был реализован bge_m3" /path/to/project | wc -c
# After timeline (rescan first so events exist)
uv run ctx pack "когда был реализован bge_m3" /path/to/project | wc -c
# Delta should be ≤ 3 KB — the budget that enrich_pack_with_timeline enforces.
```

### Step 3.3 — Fallback verification

Goal: verify that flipping the flag back to `false` makes the scanner
behave exactly as pre-spec-010.

```yaml
# ~/.lvdcp/config.yaml
timeline:
  enabled: false
```

```bash
uv run ctx scan /path/to/real/project --mode full
uv run ctx timeline status
# Expect: no new events for this scan_id; existing events remain untouched.
```

Doctor should stay PASS on all checks except `timeline store` (which becomes
PASS because the check honors `enabled: false`).

---

## 4. Rollback

Timeline is append-only. Rollback is reversible at any time; you never lose
prior analytic data.

### Soft rollback (disable, keep data)

```yaml
timeline:
  enabled: false
```

Next scan writes zero timeline events. Existing store stays on disk for
potential later re-enablement or export. MCP tools (`lvdcp_when`,
`lvdcp_removed_since`, `lvdcp_diff`) keep returning historical data.

### Hard rollback (disable, wipe store)

```bash
# with daemon stopped (launchctl unload …)
mv ~/.lvdcp/symbol_timeline.db ~/.lvdcp/symbol_timeline.db.bak.$(date +%s)
```

Next scan with `enabled: true` rebuilds the store from scratch (events for
pre-existing symbols are *not* backfilled — only changes observed from that
scan onward land). Keep the `.bak` file for at least one scan cycle in case
you need to inspect past events.

### Per-project opt-out

If one project trips on timeline but you want the feature globally, either:

- scan that project with `--no-timeline` (CLI flag honored via config
  override), or
- carve a project-level `~/.lvdcp/projects/<name>.yaml` that sets
  `timeline.enabled: false` for just that entry.

---

## 5. Observability checklist

Before declaring the rollout successful on a new machine:

- `ctx doctor` exits 0 (no FAILs, WARNs are acceptable).
- Prometheus metrics scrape non-empty (if metrics exporter is wired):
  - `symbol_timeline_events_total` is non-zero after a scan that touched code.
  - `symbol_timeline_query_latency_seconds` p95 < 100 ms on a warm store.
  - `symbol_timeline_sink_errors_total` is 0 over 24 h.
- MCP tool smoke:
  - `lvdcp_when symbol="apps.cli.main"` returns a non-empty history.
  - `lvdcp_removed_since since="HEAD~10"` returns without error (result may
    legitimately be empty).

---

## 6. Known limits

- Rename detection is heuristic; threshold 0.85 is conservative. False
  negatives (rename recorded as delete+add) are more likely than false
  positives. Adjust `rename_similarity_threshold` downward only if you are
  willing to accept more spurious rename edges in the graph.
- `retention_days` prunes on every `append`. Setting a low value on a busy
  project turns every scan into an O(events) delete pass — prefer `null`
  unless disk pressure demands pruning.
- `privacy_mode: off` retains commit bodies and docstrings verbatim. Do not
  use on multi-tenant machines.
- The store is single-writer per project. Running two agents against the
  same project root will surface the FAIL doctor check ("unopenable").

---

## 7. Contacts & references

- Spec: `specs/010-feature-timeline-index/spec.md`
- Plan: `specs/010-feature-timeline-index/plan.md`
- Tasks: `specs/010-feature-timeline-index/tasks.md`
- Store implementation: `libs/symbol_timeline/store.py`
- Sink wiring: `libs/scanning/scanner.py::_maybe_build_default_timeline_sink`
- Doctor check: `libs/mcp_ops/doctor.py::check_timeline_store`
- Perf gate: `tests/perf/test_scan_with_timeline.py` (run with `uv run pytest -m slow tests/perf`)
