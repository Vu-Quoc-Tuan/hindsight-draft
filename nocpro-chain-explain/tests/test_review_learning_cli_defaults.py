from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "materialize_training_corpus.py",
    "train_ranker.py",
    "evaluate_ranker.py",
)


@pytest.mark.parametrize("script", SCRIPTS)
def test_synthetic_source_requires_explicit_test_only_opt_in(script: str) -> None:
    result = subprocess.run(
        [sys.executable, f"scripts/review_learning/{script}", "--source", "synthetic"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--source synthetic requires --allow-synthetic" in result.stderr


@pytest.mark.parametrize("script", SCRIPTS)
def test_cli_defaults_to_postgres_not_synthetic(script: str) -> None:
    result = subprocess.run(
        [sys.executable, f"scripts/review_learning/{script}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "--database-url is required when --source is postgres" in result.stderr
