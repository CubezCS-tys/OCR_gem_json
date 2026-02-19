Brutally honest, triple check, no whistleblowers. Triple check can give me evidence, research, and reasoned approaches to everything. Fully rigorous implementations, no shortcuts. Just be brutally honest with me in chat. If you're unsure, ask me, do research, and provide me with recommendations and I can steer you. Don't just assume things; do everything objectively, rigorously, fully, end-to-end, correctly.

# Codex Operating Rules For This Repo

## Non-Negotiables
- Never claim completion without verification evidence.
- Explicitly separate facts, assumptions, and open risks.
- Prefer reproducible commands and measurable checks.
- If uncertain, state uncertainty and resolve it before final claims.

## Triple-Check Protocol
1. Verify intent and constraints before implementation.
2. Verify code behavior with direct tests/commands where possible.
3. Verify git state (branch, diff, upstream, push target) before publishing.

## Stateless Memory Workflow
- Persistent local memory lives only in `.codex/agent_logs/`.
- At session start: review recent relevant log files before major work.
- During work: log key decisions, assumptions, blockers, and validation evidence.
- At session end: append a concise summary with exact file/command references.

## Git Safety
- Do not rewrite history unless explicitly requested.
- Before any push, confirm branch ancestry and destination.
- Keep `.codex/` and `.claude/` out of git tracking.
