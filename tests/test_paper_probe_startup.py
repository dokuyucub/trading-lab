"""Run before dev installation in CI: exercise the actual workflow entrypoint."""

import os
import subprocess
import sys
import unittest
from pathlib import Path


class PaperProbeStartupTest(unittest.TestCase):
    def test_module_reaches_configuration_check_without_credentials(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-m", "tlab.data.paper_probe"],
            cwd=repo,
            env={
                **os.environ,
                "PYTHONPATH": str(repo / "src"),
                "ALPACA_PAPER_API_KEY": "",
                "ALPACA_PAPER_SECRET_KEY": "",
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "FAIL configuration: paper key and secret are required\n")
        self.assertEqual(result.stderr, "")
