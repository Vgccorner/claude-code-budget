#!/usr/bin/env python3
"""What a Claude Code session really cost: the lead thread and every subagent it spawned, from the session's own logs.

usage: session_cost.py [session | latest] [--logs DIR] [--limit TOKENS] [--json]

Reads <logs>/<session>.jsonl (the lead) and <logs>/<session>/subagents/agent-*.jsonl (one file per subagent).
<logs> defaults to the folder Claude Code uses for the current directory: ~/.claude/projects/<cwd, non-alphanumerics -> "-">.

Each model reply is counted once (the log repeats a reply once per content block).
"weighted" is one comparable number: fresh input x1, cache write x1.25, cache read x0.1, output x5.
Those are list-price ratios, so read it as an estimate, not billing.
"""
import argparse
import json
import re
import sys
from pathlib import Path

WEIGHTS = {'input': 1.0, 'cache_write': 1.25, 'cache_read': 0.1, 'output': 5.0}
DEFAULT_LIMIT = 200_000


def default_logs(cwd=None):
    """The folder Claude Code keeps this directory's session logs in."""
    cwd = str(Path(cwd or Path.cwd()).resolve())
    return Path.home() / '.claude' / 'projects' / re.sub(r'[^a-zA-Z0-9]', '-', cwd)


def tally(path):
    """Token totals for one thread (one .jsonl file)."""
    replies = {}
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        msg = row.get('message') if isinstance(row, dict) else None
        if not isinstance(msg, dict):
            continue
        use = msg.get('usage')
        if row.get('type') != 'assistant' or not isinstance(use, dict) or not msg.get('id'):
            continue
        replies[msg['id']] = (use, msg.get('model') or '?')  # the last copy of a reply carries its final usage
    out = {'model': '?', 'turns': len(replies), 'input': 0, 'cache_write': 0, 'cache_read': 0, 'output': 0, 'peak_context': 0}
    for use, model in replies.values():
        fresh, write, read = (use.get(k) or 0 for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
        out['input'] += fresh
        out['cache_write'] += write
        out['cache_read'] += read
        out['output'] += use.get('output_tokens') or 0
        out['peak_context'] = max(out['peak_context'], fresh + write + read)
        out['model'] = model
    out['weighted'] = round(sum(out[k] * w for k, w in WEIGHTS.items()))
    return out


def read_role(sub):
    """The subagent's role name from its .meta.json, or '?' when the log has none."""
    meta = sub.with_name(sub.stem + '.meta.json')
    try:
        return json.loads(meta.read_text(encoding='utf-8')).get('agentType') or '?'
    except (OSError, ValueError, AttributeError):
        return '?'


def pick_session(logs, want):
    if want != 'latest':
        log = logs / f'{want}.jsonl'
        if not log.is_file():
            sys.exit(f'No log for session {want} in {logs}. Pass a session id from that folder, or "latest".')
        return log
    found = sorted(logs.glob('*.jsonl'), key=lambda p: p.stat().st_mtime)
    if not found:
        sys.exit(f'No session logs in {logs}. Run this from a project Claude Code has been used in, or pass --logs DIR.')
    return found[-1]


def build_report(log, limit=DEFAULT_LIMIT):
    log = Path(log)
    lead = {'thread': 'lead', 'role': 'lead', **tally(log)}
    agents = []
    for sub in sorted((log.parent / log.stem / 'subagents').glob('agent-*.jsonl')):
        agents.append({'thread': sub.stem.removeprefix('agent-'), 'role': read_role(sub), **tally(sub)})
    threads = [lead] + agents
    for t in threads:
        t['over_limit'] = t['peak_context'] > limit
    total = sum(t['weighted'] for t in threads)
    return {
        'session': log.stem,
        'limit': limit,
        'threads': threads,
        'weighted_total': total,
        'lead_share': round(lead['weighted'] / total, 2) if total else 0,
        'over_limit': [t['thread'] for t in threads if t['over_limit']],
    }


def render(report):
    row = '{:<20} {:<22} {:>5} {:>9} {:>11} {:>11} {:>8} {:>9} {:>10}'
    lines = [f"session {report['session']}",
             row.format('thread', 'model', 'turns', 'input', 'cache write', 'cache read', 'output', 'peak ctx', 'weighted')]
    for t in report['threads']:
        name = t['thread'] if t['thread'] == 'lead' else f"{t['role']} {t['thread']}"
        flag = '  <- over limit' if t['over_limit'] else ''
        lines.append(row.format(name[:20], t['model'][:22], t['turns'], f"{t['input']:,}", f"{t['cache_write']:,}",
                                f"{t['cache_read']:,}", f"{t['output']:,}", f"{t['peak_context']:,}", f"{t['weighted']:,}") + flag)
    lines.append(f"weighted total {report['weighted_total']:,}; the lead is {report['lead_share']:.0%} of it")
    if report['over_limit']:
        lines.append(f"OVER the {report['limit']:,}-token context limit: {', '.join(report['over_limit'])}. "
                     'Hand off to a fresh thread instead of continuing it.')
    else:
        lines.append(f"No thread passed the {report['limit']:,}-token context limit.")
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Token cost of a Claude Code session, per thread.')
    ap.add_argument('session', nargs='?', default='latest', help='session id, or "latest" (default)')
    ap.add_argument('--logs', type=Path, help='project log folder (default: derived from the current directory)')
    ap.add_argument('--limit', type=int, default=DEFAULT_LIMIT, help=f'flag threads whose peak context passes this (default {DEFAULT_LIMIT:,})')
    ap.add_argument('--json', action='store_true', help='print the report as JSON')
    args = ap.parse_args(argv)
    logs = (args.logs or default_logs()).expanduser()
    if not logs.is_dir():
        sys.exit(f'No log folder at {logs}. Pass --logs DIR, or run this from a directory Claude Code has been used in.')
    report = build_report(pick_session(logs, args.session), args.limit)
    print(json.dumps(report, indent=1) if args.json else render(report))


if __name__ == '__main__':
    main()
