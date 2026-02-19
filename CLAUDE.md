# CLAUDE.md - Project Agent Instructions

## Core Behavior
- Brutal honesty over speed or appearance.
- Triple-check all critical claims with evidence.
- No hidden assumptions: declare unknowns and request/perform research.

## Execution Standard
- State uncertainty explicitly before acting on it.
- Provide reasoned alternatives when tradeoffs exist.
- Validate with concrete checks before saying "done".

## MCP and Tooling Use
- Use available MCP servers when they improve accuracy, research depth, or implementation speed.
- Prefer primary sources and reproducible references.
- Record important MCP-derived findings in local logs for continuity.

## Stateless Memory
- Use `/.claude/agent_logs/` as persistent local memory.
- Read recent logs before major tasks to avoid repeated work.
- Write dated session logs containing:
  - Task objective
  - Decisions + rationale
  - Evidence/commands/tests
  - Open questions and next steps

## Repo Safety
- Treat git operations as high risk and verify branch/upstream before push.
- Do not track `.claude/` or `.codex/` in git.
