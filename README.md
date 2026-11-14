# claude-code-budget

Tools for running multi-agent Claude Code work on a token budget: a cost report per thread, a hook that stops subagents from silently inheriting the lead's costly model, and a guide to when to spawn agents at all.
Python 3.10+, standard library only, no API calls.

## Case study

I run a multi-agent pipeline that writes, renders and publishes YouTube Shorts. I measured 400 subagent logs from it (2026-11-05 to 11-10) and found:

- Every agent starts at about 59k tokens before it reads its brief. A two-turn reader costs about 120k; a typical builder (about 7 turns, ending near 90k of context) costs about 0.5M.
- Builders resumed for fix rounds grew to 700-970k of context.
- On early videos the lead thread re-reading 470-585k tokens per turn was 36-72% of the cost.

The redesign: one director builder with a fixed brief, at most one fix round done by a fresh builder (never a resumed one), models routed by role, and new character assets built on their own line.

| One video's production run | Before | Predicted | After |
|---|---|---|---|
| Agents | about 30 | 6 | 6 |
| Renders | 6 | 2 | 1 |
| Agent tokens | about 6.7M | 1.5M | about 1.1M |

That is about 84% fewer tokens per run. The next video also ran on 6 agents and about 1.1M, under the same 1.5M budget. Its new-asset work (about 2.1M) ran on its own line and is **not** in that 1.1M. The "before" run also included 7 fresh picture reviews, which the redesign cut.

The method is in [docs/orchestration-guide.md](docs/orchestration-guide.md); the role files are in [agents/](agents/).

## Quick start

```bash
# cost of the latest session in the current project (log folder derived from the cwd)
python3 session_cost.py latest

# a specific session, another project, a stricter limit, JSON out
python3 session_cost.py <session-id> --logs ~/.claude/projects/<project> --limit 150000 --json

# tests
python3 -m unittest
```

Per thread (the lead, then each subagent) it prints model, turns, input, cache-write, cache-read and output tokens, peak context and a weighted estimate. Then the total, the lead's share, and a flag on every thread whose peak context passed `--limit` (default 200,000). Each model reply is counted once, although the log repeats a reply per content block.

Weighted = fresh input x1 + cache write x1.25 + cache read x0.1 + output x5. These are list-price ratios, so it is one comparable number, not a bill.

### Sample output

From the synthetic fixture in `tests/fixtures/project`:

```
session 11111111-2222-3333-4444-555555555555
thread               model                  turns     input cache write  cache read   output  peak ctx   weighted
lead                 claude-opus-5-5            4        18      75,000     187,000    4,000    75,006    132,468
worker a1b2c3        claude-sonnet-5-5          5        15     237,000     485,000   11,300   240,003    401,265  <- over limit
bulk d4e5f6          claude-haiku-5-5           2         5      62,000      59,000      800    62,002     87,405
weighted total 621,138; the lead is 21% of it
OVER the 200,000-token context limit: a1b2c3. Hand off to a fresh thread instead of continuing it.
```

## The hook

[hooks/require_model.py](hooks/require_model.py) is a `PreToolUse` hook for the subagent tool (`Agent`, and the older name `Task`). A spawn that sets no `model` inherits the lead's model, which is usually the costliest. The hook denies it unless either:

- the call sets `model` (anything but `inherit`), or
- `subagent_type` is an allowlisted role whose agent file (`.claude/agents/<role>.md`, project then user) pins a `model:`.

The deny reason says what to add. The allowlist defaults to `orchestrator,worker,bulk`; set `CLAUDE_BUDGET_ROLES` to change it. Copy the hook to `.claude/hooks/` and merge [hooks/settings.example.json](hooks/settings.example.json) into `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Agent|Task",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PROJECT_DIR}/.claude/hooks/require_model.py\""
          }
        ]
      }
    ]
  }
}
```

It reads the hook JSON on stdin and answers with `hookSpecificOutput.permissionDecision: "deny"` plus a reason, per the [hooks reference](https://code.claude.com/docs/en/hooks). Agent file fields (`model`, `effort`) follow the [subagents docs](https://code.claude.com/docs/en/sub-agents). Role defaults are plain `model:` lines in [agents/](agents/): Orchestrator = Opus, Worker = Sonnet, Bulk = Haiku. Edit them to change the mapping. If the hook input is unreadable, the hook allows the call rather than block all work.

## Limits

- Weighted numbers are estimates from list-price ratios, not billing. A subscription's own weighting is not published.
- The log format is Claude Code's, not a stable API: it can change. The CLI skips lines it cannot parse and reads `usage`, `message.id` and `model` per reply, plus `<session>/subagents/agent-*.jsonl` and each file's `.meta.json` `agentType`. If those move, the report will undercount; check it against a known session.
- The case-study figures are my own measurements of one pipeline. Yours will differ; run the CLI on your logs.
- The hook finds agent files in the project and user folders only, not in plugins. An agent whose file lives elsewhere must pass `model` on the call.

## License

MIT, see [LICENSE](LICENSE).
