#!/usr/bin/env python3
"""PreToolUse hook: deny a subagent spawn that would silently inherit the lead's model.

A spawn passes when it sets `model`, or its `subagent_type` is an allowlisted role whose agent file pins a model.
Anything else is denied with a reason that says what to add.

Allowlist: env CLAUDE_BUDGET_ROLES, comma separated (default: orchestrator,worker,bulk).
Agent files are looked up in <project>/.claude/agents/ and ~/.claude/agents/ (project first).
Fails open on unreadable input: a broken hook should not stop all work.
"""
import json
import os
import sys
from pathlib import Path

DEFAULT_ROLES = 'orchestrator,worker,bulk'
SPAWN_TOOLS = ('Agent', 'Task')  # Task is the pre-2.1.63 name; settings and logs may still use it


def pinned_model(role, project_dirs):
    """The model pinned in the role's agent file, or '' when the file is missing or leaves it to inherit."""
    for base in [*project_dirs, Path.home()]:
        path = Path(base) / '.claude' / 'agents' / f'{role}.md'
        if not path.is_file():
            continue
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        if not lines or lines[0].strip() != '---':
            return ''
        for line in lines[1:]:
            if line.strip() == '---':
                break
            key, _, value = line.partition(':')
            if key.strip() == 'model':
                value = value.strip().strip('"\'')
                return '' if value in ('', 'inherit') else value
        return ''
    return ''


def check(event):
    """Return the deny reason for this hook input, or None to let the call through."""
    if event.get('tool_name') not in SPAWN_TOOLS:
        return None
    args = event.get('tool_input') or {}
    model = str(args.get('model') or '').strip()
    if model and model != 'inherit':
        return None
    roles = [r.strip() for r in os.environ.get('CLAUDE_BUDGET_ROLES', DEFAULT_ROLES).split(',') if r.strip()]
    role = str(args.get('subagent_type') or '').strip()
    project_dirs = [d for d in (os.environ.get('CLAUDE_PROJECT_DIR'), event.get('cwd')) if d]
    if role in roles:
        if pinned_model(role, project_dirs):
            return None
        return (f'Subagent spawn blocked: the "{role}" agent file does not pin a model, so it would inherit the lead\'s. '
                f'Add a `model:` line (sonnet, opus or haiku) to {role}.md, or pass model on this call.')
    return ('Subagent spawn blocked: no model is set, so this agent would inherit the lead\'s (usually the costliest). '
            'Add model: "haiku", "sonnet" or "opus" to this call, or set subagent_type to one of '
            f'{", ".join(roles)} (each pins its own model).')


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(event, dict):
        return
    reason = check(event)
    if reason:
        print(json.dumps({'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': reason,
        }}))


if __name__ == '__main__':
    main()
