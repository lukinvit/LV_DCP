# LV_DCP Claude Code skill

This directory ships a drop-in Claude Code skill that teaches the agent to
use LV_DCP's MCP tools before grepping or reading multiple files.

## Install

Copy the `lvdcp/` directory into your Claude Code configuration:

```bash
# Per-user (all projects)
cp -r skills/lvdcp ~/.claude/skills/

# Per-project (this repo only)
cp -r skills/lvdcp .claude/skills/
```

Claude Code auto-discovers skills under those paths and makes them
invokable via the `Skill` tool.

## What it does

The skill documents the eight LV_DCP MCP tools, the retrieval-order
contract (pack first, targeted reads second, graph follow-up only when
needed), and the "do not proceed on ambiguous coverage" rule that the
MCP server already surfaces in pack warnings.

## Prerequisites

- LV_DCP MCP server configured in Claude Code (`ctx mcp install` or
  via `.mcp.json`).
- At least one project scanned (`ctx scan <path>`). The skill includes
  a check — the tools return a typed error for un-indexed projects.

## Aligned with MCP 2026

This skill is the "Skills over MCP" pattern referenced in the
[MCP 2026 roadmap](https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/):
tool descriptions are exhaustive, but the skill adds the workflow layer
that tool descriptions alone can't carry.
