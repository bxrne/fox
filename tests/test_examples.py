"""Smoke-test the documented example commands in subprocesses."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_python(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_contract_cli_checks_only_the_public_function() -> None:
    assert run_python("-m", "fox", "examples/contracts.py") == "fox checked 1 pure function(s)\n"


def test_contract_example_finds_the_generated_rounding_bug() -> None:
    output = run_python("examples/contracts.py")
    assert "Generated check caught the floor-only split dropping remainder cents." in output


def test_effects_example_checks_fakes_and_local_io() -> None:
    output = run_python("examples/effects.py")
    assert "Generated checks passed with separate dict-backed read/write handlers." in output
    assert "Scoped override: Preview copy" in output
    assert "Local round-trip: Hello from a local file." in output


def test_effects_example_keeps_local_io_under_optimization() -> None:
    output = run_python("-O", "examples/effects.py")
    assert "Production mode: generated checks and interception are disabled." in output
    assert "Local round-trip: Hello from a local file." in output
