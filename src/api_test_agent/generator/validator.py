"""Validates generated code files for syntax and structural correctness."""

import ast
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

COLLECT_TIMEOUT_SECONDS = 30


def validate_python(files: dict[str, str]) -> dict[str, str]:
    """Check Python files for syntax errors.

    Returns dict of {filename: error_message} for files with errors.
    """
    errors = {}
    for filename, content in files.items():
        if not filename.endswith(".py"):
            continue
        if not content.strip():
            continue
        try:
            ast.parse(content, filename=filename)
        except SyntaxError as e:
            errors[filename] = f"SyntaxError: {e.msg} (line {e.lineno})"
    return errors


def validate_yaml(files: dict[str, str]) -> dict[str, str]:
    """Check YAML files for format errors.

    Returns dict of {filename: error_message} for files with errors.
    """
    errors = {}
    for filename, content in files.items():
        if not filename.endswith((".yaml", ".yml")):
            continue
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            errors[filename] = f"YAMLError: {e}"
    return errors


def validate_collect(files: dict[str, str]) -> dict[str, str]:
    """Run pytest --collect-only to verify tests can be discovered.

    Writes files to a temp directory and runs pytest collection.
    Returns dict of {filename: error_message} for files with errors.
    """
    test_files = {f: c for f, c in files.items() if f.endswith(".py") and c.strip()}
    if not test_files:
        return {}

    errors = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        for filename, content in files.items():
            filepath = tmppath / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "--collect-only",
                    "-q",
                    str(tmppath),
                ],
                capture_output=True,
                text=True,
                cwd=tmpdir,
                timeout=COLLECT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return {
                "_collect": (
                    "pytest collection timed out after "
                    f"{COLLECT_TIMEOUT_SECONDS} seconds"
                )
            }
        if result.returncode != 0:
            stderr = result.stderr + result.stdout
            for filename in test_files:
                if filename in stderr:
                    lines = [
                        line
                        for line in stderr.splitlines()
                        if filename in line or "ERROR" in line or "Error" in line
                    ]
                    errors[filename] = "\n".join(lines[:5]) if lines else stderr[:500]
            if not errors and stderr.strip():
                errors["_collect"] = stderr[:500]
    return errors


def validate_files(files: dict[str, str]) -> dict[str, str]:
    """Run all validations on generated files.

    Returns dict of {filename: error_message} for all files with errors.
    Runs syntax/YAML checks first, then pytest collect only if syntax passes.
    """
    errors = {}
    errors.update(validate_python(files))
    errors.update(validate_yaml(files))

    if not errors:
        errors.update(validate_collect(files))

    return errors
