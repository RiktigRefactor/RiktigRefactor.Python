"""Runs the programs of test cases: `main.py` in a directory must exit with status 0."""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROGRAM_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class ProgramOutcome:
    passed: bool
    output: str


def run_program(directory: Path, python_path: list[str] | None = None) -> ProgramOutcome:
    """Runs `main.py` with the interpreter that runs the tests, in `directory`.

    Not `-I`: isolated mode removes the script's directory from `sys.path`, so multi-file programs could not import
    each other. `-s` keeps user site-packages out, and `-B` keeps `__pycache__` out of the case directories.
    """
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("PYTHON")
    }
    if python_path:
        environment["PYTHONPATH"] = os.pathsep.join(str(directory / entry) for entry in python_path)
    entry_point = directory / "main.py"
    if not entry_point.exists():
        return ProgramOutcome(False, "the program has no main.py")
    try:
        completed = subprocess.run(
            [sys.executable, "-s", "-B", "main.py"],
            cwd=directory,
            env=environment,
            capture_output=True,
            text=True,
            timeout=PROGRAM_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return ProgramOutcome(False, "the program timed out")
    return ProgramOutcome(completed.returncode == 0, completed.stdout + completed.stderr)
