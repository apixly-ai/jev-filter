"""Benchmark parallelism is caller-bounded, including shared-team runs."""

import json
import subprocess
import sys


def test_batch_benchmark_accepts_a_lower_parallel_budget(tmp_path):
    target = tmp_path / "report.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.run",
            "--records",
            "8",
            "--parallel-workers",
            "6",
            "--output",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    data = json.loads(target.read_text())
    assert data["parallel_workers"] == 6
    assert all(row["requested_workers"] == 6 for row in data["runs"] if "parallel" in row["name"])
