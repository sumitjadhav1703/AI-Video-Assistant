import time
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from backend import jobs
from backend.core import llm_gateway

SEGMENT = {'text': 'The team agreed on a budget.', 'start_ms': 0, 'end_ms': 1000, 'timing_precision': 'segment'}
FINDINGS = {'action_items': 'a', 'key_decisions': 'k', 'open_questions': 'o'}
DELAY = 0.2


def slow(value):
    def work(*args, **kwargs):
        time.sleep(DELAY)
        return value
    return work


class ConcurrentStageTests(unittest.TestCase):
    def run_job(self, **overrides):
        stages = {'generate_title': slow('title'), 'summarize': slow('summary'),
                  'extract_findings': slow(FINDINGS), 'build_rag_chain': slow(None), **overrides}
        with ExitStack() as stack:
            for name, value in (('require_provider_calls', None), ('preflight_processing', None), ('cleanup', None)):
                stack.enter_context(patch.object(jobs, name, return_value=value))
            stack.enter_context(patch.object(jobs, 'process_input', return_value=(['audio'], [])))
            stack.enter_context(patch.object(jobs, 'transcribe_segments', return_value=[SEGMENT]))
            for name, side_effect in stages.items():
                stack.enter_context(patch.object(jobs, name, side_effect=side_effect))
            steps = stack.enter_context(patch.object(jobs.db, 'set_step'))
            finish = stack.enter_context(patch.object(jobs.db, 'finish_job'))
            fail = stack.enter_context(patch.object(jobs.db, 'fail_job'))
            delete = stack.enter_context(patch.object(jobs, 'delete_vector_store'))
            started = time.monotonic()
            jobs.run_job('job-1', 'clip.mp3')
            return time.monotonic() - started, [c.args[1] for c in steps.call_args_list], finish, fail, delete

    def test_note_stages_overlap_and_keep_results(self):
        elapsed, _, finish, fail, _ = self.run_job()
        fail.assert_not_called()
        self.assertLess(elapsed, 3 * DELAY, 'four stages of 0.2 s ran one after another')
        saved = finish.call_args.args[1]
        self.assertEqual((saved['title'], saved['summary'], saved['action_items']), ('title', 'summary', 'a'))

    def test_progress_moves_forward_in_order(self):
        _, steps, *_ = self.run_job()
        order = [jobs.STEPS.index(step) for step in steps]
        self.assertEqual(order, sorted(order))
        self.assertEqual(steps[:3], ['audio', 'transcript', 'title'])

    def test_workers_see_the_job_operation_scope(self):
        seen = []

        def title(transcript):
            seen.append(llm_gateway.current_operation())
            return 'title'

        _, _, _, fail, _ = self.run_job(generate_title=title)
        fail.assert_not_called()
        self.assertEqual(seen, ['job-1'])

    def test_failure_waits_for_indexing_then_removes_vectors(self):
        finished = []

        def index(*args, **kwargs):
            time.sleep(DELAY)
            finished.append('rag')

        def broken(transcript):
            raise RuntimeError('provider down')

        _, _, finish, fail, delete = self.run_job(generate_title=broken, build_rag_chain=index)
        finish.assert_not_called()
        fail.assert_called_once()
        self.assertEqual(finished, ['rag'], 'cleanup ran before indexing finished')
        delete.assert_called_once_with('job-1')


if __name__ == '__main__':
    unittest.main()
