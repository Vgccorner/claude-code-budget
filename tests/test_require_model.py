import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / 'hooks' / 'require_model.py'


class RequireModelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / 'project'
        agents = self.project / '.claude' / 'agents'
        agents.mkdir(parents=True)
        (agents / 'worker.md').write_text('---\nname: worker\nmodel: sonnet\n---\nBuild.\n')
        (agents / 'drifter.md').write_text('---\nname: drifter\nmodel: inherit\n---\nUnpinned.\n')

    def run_hook(self, tool_name, tool_input, roles=None, raw=None):
        env = {**os.environ, 'HOME': self.tmp.name, 'CLAUDE_PROJECT_DIR': str(self.project)}
        env.pop('CLAUDE_BUDGET_ROLES', None)
        if roles:
            env['CLAUDE_BUDGET_ROLES'] = roles
        event = raw if raw is not None else json.dumps({'hook_event_name': 'PreToolUse', 'cwd': str(self.project),
                                                       'tool_name': tool_name, 'tool_input': tool_input})
        done = subprocess.run([sys.executable, str(HOOK)], input=event, capture_output=True, text=True, env=env, check=True)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def assertDenied(self, out, *words):
        decision = out['hookSpecificOutput']
        self.assertEqual(decision['hookEventName'], 'PreToolUse')
        self.assertEqual(decision['permissionDecision'], 'deny')
        for word in words:
            self.assertIn(word, decision['permissionDecisionReason'])

    def test_allows_explicit_model(self):
        self.assertIsNone(self.run_hook('Agent', {'prompt': 'x', 'model': 'haiku'}))

    def test_allows_allowlisted_role_with_pinned_model(self):
        self.assertIsNone(self.run_hook('Agent', {'prompt': 'x', 'subagent_type': 'worker'}))

    def test_denies_spawn_with_no_model_and_no_role(self):
        self.assertDenied(self.run_hook('Agent', {'prompt': 'x'}), 'model', 'worker')

    def test_denies_general_purpose(self):
        self.assertDenied(self.run_hook('Agent', {'prompt': 'x', 'subagent_type': 'general-purpose'}), 'subagent_type')

    def test_denies_inherit(self):
        self.assertDenied(self.run_hook('Agent', {'prompt': 'x', 'model': 'inherit'}))

    def test_denies_allowlisted_role_that_inherits(self):
        out = self.run_hook('Agent', {'prompt': 'x', 'subagent_type': 'drifter'}, roles='drifter')
        self.assertDenied(out, 'drifter', 'model:')

    def test_denies_allowlisted_role_with_missing_file(self):
        self.assertDenied(self.run_hook('Agent', {'prompt': 'x', 'subagent_type': 'bulk'}), 'bulk')

    def test_denies_role_not_on_allowlist(self):
        self.assertDenied(self.run_hook('Agent', {'prompt': 'x', 'subagent_type': 'worker'}, roles='orchestrator'))

    def test_accepts_old_task_tool_name(self):
        self.assertDenied(self.run_hook('Task', {'prompt': 'x'}))
        self.assertIsNone(self.run_hook('Task', {'prompt': 'x', 'model': 'opus'}))

    def test_ignores_other_tools(self):
        self.assertIsNone(self.run_hook('Bash', {'command': 'ls'}))

    def test_fails_open_on_bad_input(self):
        self.assertIsNone(self.run_hook('', {}, raw='not json'))


if __name__ == '__main__':
    unittest.main()
