# Phase 8 — Native Onboarding

**Status:** Implemented 2026-04-13
**Owner:** Vladimir Lukin
**Follows:** Phase 7C / Phase 7D
**Version target:** 0.7.x

## 1. Goal

Turn LV_DCP setup for a new user and a new project into one guided command that
assembles the working baseline without requiring internal project knowledge.

**Litmus test:** a new user can run `ctx setup /path/to/project --open-ui` and
end up with:

- the project registered and scanned
- MCP and Claude hooks installed
- wiki generation attempted or clearly explained
- background watching enabled or explicitly skipped
- a final readiness summary that states whether the install is in `base mode`
  or `full mode`

## 2. Problem

The current install story is functionally complete but operationally fragmented:

- `ctx mcp install`
- `ctx scan /path`
- `ctx watch add /path` / `ctx watch install-service`
- `ctx wiki update /path`
- `ctx ui /path`

An experienced maintainer can assemble these pieces. A new user cannot do this
reliably without reading internal docs.

There is also an important capability mismatch that is not made explicit enough:

- `base mode` works with local scan/index/status capabilities
- `full mode` requires `Qdrant + real embeddings`
- wiki generation requires `Claude CLI`

Without a clear orchestration layer, users discover missing capabilities only
after degraded results.

## 3. Scope

### In scope

- a new `ctx setup` command as the primary onboarding entrypoint
- explicit `base mode` vs `full mode` readiness summary
- project registration + initial scan as part of setup
- MCP install + hook install as part of setup
- wiki enablement + initial wiki build attempt as part of setup
- optional background service install
- optional UI launch

### Out of scope

- Homebrew / PyPI / installer packaging
- Linux service-manager parity beyond the current launchd-first path
- automatic secret provisioning
- fully interactive wizard UI

## 4. Design

### 4.1 Setup orchestration

Add:

```bash
ctx setup /absolute/path/to/project
```

Default behavior:

1. ensure config exists
2. install MCP and hooks on a best-effort basis
3. register + scan the target project
4. enable wiki defaults in config
5. attempt initial wiki build if `claude` is available
6. optionally install background service
7. print a readiness summary

Optional behavior:

- `--open-ui` launches the local dashboard at the end
- `--install-service/--no-install-service` controls launchd registration
- `--wiki/--no-wiki` controls initial wiki enablement/build
- `--scope user|project|local` forwards MCP install scope

### 4.2 Readiness summary

`ctx setup` must finish with explicit capability reporting:

- project index ready or failed
- MCP integration ready / degraded
- hooks ready / degraded
- wiki ready / degraded
- background service ready / skipped / degraded
- full retrieval ready / degraded

`full retrieval` is only considered ready when:

- Qdrant is enabled
- Qdrant is reachable
- embedding provider is not `fake`
- required embedding API key or endpoint is configured

Wiki is only considered ready when:

- wiki is enabled
- `claude` CLI is available
- initial wiki generation completed successfully

### 4.3 Base mode vs full mode

The setup summary must explicitly educate the user:

- `base mode` = scan + status + packs + hooks/UI baseline
- `full mode` = hybrid/vector retrieval and best retrieval quality

This makes the dependency contract visible at the first-run boundary instead of
hiding it in docs or later failures.

## 5. Acceptance Criteria

1. `ctx setup /path --no-open-ui` registers and scans a valid project in one run.
2. `ctx setup` can install MCP/hooks on a best-effort basis without aborting the
   whole setup if Claude CLI is unavailable.
3. The final summary explicitly reports that `full mode` requires Qdrant and a
   real embedding provider/API key.
4. If wiki generation cannot run because `claude` is unavailable, the summary
   states that clearly.
5. `ruff`, `mypy`, and CLI tests remain green.
