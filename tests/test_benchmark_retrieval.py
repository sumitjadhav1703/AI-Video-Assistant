import unittest

from scripts.benchmark_retrieval import metrics


class BenchmarkTests(unittest.TestCase):
    def test_metrics_are_bounded_and_use_relevant_ranks(self):
        self.assertEqual(metrics(['b', 'a', 'c'], {'a', 'c'}, 2),
                         {'recall_at_k': 0.5, 'reciprocal_rank': 0.5})
        self.assertEqual(metrics([], {'a'}, 2), {'recall_at_k': 0.0, 'reciprocal_rank': 0.0})


if __name__ == '__main__':
    unittest.main()
