import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.benchmark_retrieval import metrics
from scripts import benchmark_recruiter_demo


class BenchmarkTests(unittest.TestCase):
    def test_metrics_are_bounded_and_use_relevant_ranks(self):
        self.assertEqual(metrics(['b', 'a', 'c'], {'a', 'c'}, 2),
                         {'recall_at_k': 0.5, 'reciprocal_rank': 0.5})
        self.assertEqual(metrics([], {'a'}, 2), {'recall_at_k': 0.0, 'reciprocal_rank': 0.0})

    def test_recruiter_benchmark_reads_cgroup_limits_and_counters(self):
        with TemporaryDirectory() as directory, patch.object(
                benchmark_recruiter_demo, 'CGROUP_ROOT', Path(directory), create=True), \
                patch.object(benchmark_recruiter_demo.sys, 'platform', 'linux'):
            files = {'memory.max': '536870912', 'memory.swap.max': '0', 'cpu.max': '10000 100000',
                     'memory.peak': '333333333', 'memory.events': 'low 0\nmax 1\noom 0\noom_kill 0',
                     'cpu.stat': 'usage_usec 123456\nuser_usec 100000'}
            for filename, value in files.items():
                (Path(directory) / filename).write_text(value)
            self.assertEqual(benchmark_recruiter_demo.container_limits(),
                             {'memory_limit_bytes': 536870912, 'swap_limit_bytes': 0, 'cpus': 0.1})
            self.assertEqual(benchmark_recruiter_demo.container_usage(),
                             {'peak_bytes': 333333333, 'events': {'low': 0, 'max': 1, 'oom': 0, 'oom_kill': 0},
                              'cpu_usage_usec': 123456})


if __name__ == '__main__':
    unittest.main()
