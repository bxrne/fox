import subprocess
import sys
from pathlib import Path

import pytest

from fox.__main__ import _load


def test_file_targets_import_siblings_outside_the_working_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "sibling.py").write_text("def increment(n):\n    return n + 1\n")
    subject = project / "subject.py"
    subject.write_text(
        "from fox import fox\n"
        "from sibling import increment\n"
        "@fox(ensures=lambda n, result: result == n + 1)\n"
        "def run(n: int) -> int:\n"
        "    return increment(n)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "fox", str(subject)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "fox checked 1 pure function(s)"


def test_file_loading_restores_import_path_on_error(tmp_path: Path) -> None:
    subject = tmp_path / "broken.py"
    subject.write_text("raise ValueError('broken import')\n")
    previous_path = sys.path[:]
    with pytest.raises(ValueError, match="broken import"):
        _load(str(subject))
    assert sys.path == previous_path


def test_module_targets_are_supported(tmp_path: Path) -> None:
    (tmp_path / "subject.py").write_text(
        "from fox import fox\n"
        "@fox(ensures=lambda n, result: n == result)\n"
        "def identity(n: int) -> int:\n"
        "    return n\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "fox", "subject"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "fox checked 1 pure function(s)"


def test_optimized_cli_refuses_to_claim_that_contracts_ran(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-O", "-m", "fox", "unused"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Run this without -O" in result.stderr
