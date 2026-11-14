import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import session_cost

FIXTURES = Path(__file__).parent / 'fixtures' / 'project'
SESSION = '11111111-2222-3333-4444-555555555555'


class TallyTest(unittest.TestCase):
    def test_repeated_content_blocks_count_once(self):
        lead = session_cost.tally(FIXTURES / f'{SESSION}.jsonl')
        self.assertEqual(lead['turns'], 4)
        self.assertEqual(lead['output'], 400 + 900 + 1200 + 1500)  # the final copy of each reply, not the partial one
        self.assertEqual(lead['cache_write'], 58000 + 2000 + 9000 + 6000)

    def test_weighted_estimate(self):
        lead = session_cost.tally(FIXTURES / f'{SESSION}.jsonl')
        expected = round(lead['input'] + 1.25 * lead['cache_write'] + 0.1 * lead['cache_read'] + 5 * lead['output'])
        self.assertEqual(lead['weighted'], expected)

    def test_peak_context_is_the_largest_single_turn(self):
        self.assertEqual(session_cost.tally(FIXTURES / f'{SESSION}.jsonl')['peak_context'], 6 + 6000 + 69000)


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.report = session_cost.build_report(FIXTURES / f'{SESSION}.jsonl')

    def test_lead_and_two_subagents(self):
        self.assertEqual([t['role'] for t in self.report['threads']], ['lead', 'worker', 'bulk'])
        self.assertEqual([t['model'] for t in self.report['threads']],
                         ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'])

    def test_only_the_long_worker_is_over_the_limit(self):
        self.assertEqual(self.report['over_limit'], ['a1b2c3'])

    def test_lower_limit_flags_more_threads(self):
        report = session_cost.build_report(FIXTURES / f'{SESSION}.jsonl', limit=70_000)
        self.assertEqual(report['over_limit'], ['lead', 'a1b2c3'])

    def test_totals_and_lead_share(self):
        total = sum(t['weighted'] for t in self.report['threads'])
        self.assertEqual(self.report['weighted_total'], total)
        self.assertEqual(self.report['lead_share'], round(self.report['threads'][0]['weighted'] / total, 2))


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            session_cost.main([*args, '--logs', str(FIXTURES)])
        return out.getvalue()

    def test_text_output_flags_over_limit(self):
        text = self.run_cli('latest')
        self.assertIn('<- over limit', text)
        self.assertIn('weighted total', text)

    def test_json_output(self):
        data = json.loads(self.run_cli(SESSION, '--json', '--limit', '1000000'))
        self.assertEqual(data['session'], SESSION)
        self.assertEqual(data['over_limit'], [])

    def test_unknown_session_exits_with_a_fix(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_cli('no-such-session')
        self.assertIn('Pass a session id', str(ctx.exception))

    def test_default_log_folder_follows_claude_code_naming(self):
        folder = session_cost.default_logs('/some/project.dir')
        self.assertEqual(folder.name, '-some-project-dir')


if __name__ == '__main__':
    unittest.main()
