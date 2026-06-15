"""Shared helpers for LLM-backed code generators."""

import keyword
import re
from collections.abc import Callable
from pathlib import Path

from api_test_agent.generator.validator import validate_files

MAX_RETRIES = 2


class GenerationError(RuntimeError):
    """Base error for generated artifact failures."""


class DuplicateGeneratedFileError(GenerationError):
    """Raised when multiple generation units target the same file."""


class GenerationValidationError(GenerationError):
    """Raised when generated files remain invalid after repair attempts."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        details = "; ".join(f"{name}: {message}" for name, message in errors.items())
        super().__init__(f"Generated files failed validation: {details}")


RepairFiles = Callable[[dict[str, str], dict[str, str]], dict[str, str]]


def validate_and_repair(
    files: dict[str, str], repair: RepairFiles, max_retries: int = MAX_RETRIES
) -> dict[str, str]:
    """Validate generated files and repair failures up to max_retries times."""
    current = dict(files)
    for attempt in range(max_retries + 1):
        errors = validate_files(current)
        if not errors:
            return current
        if attempt == max_retries:
            raise GenerationValidationError(errors)

        repaired = repair(dict(current), errors)
        if repaired == current:
            raise GenerationValidationError(errors)
        current = repaired

    raise AssertionError("unreachable")


def extract_fenced_content(response: str, language: str = "python") -> str:
    """Extract a fenced block, falling back to the full response."""
    pattern = rf"```{re.escape(language)}\s*\n(.*?)```"
    match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else response.strip()


def extract_declared_filename(content: str, default: str, allowed_pattern: str) -> str:
    """Read a safe filename from the first-line comment or use default."""
    first_line = content.splitlines()[0] if content else ""
    match = re.search(r"#\s*(\S+)", first_line)
    if not match:
        return default

    filename = match.group(1)
    if Path(filename).name != filename or not re.fullmatch(allowed_pattern, filename):
        return default
    return filename


def add_generated_file(files: dict[str, str], path: str, content: str) -> None:
    """Add a generated file without silently replacing an earlier result."""
    if path in files:
        raise DuplicateGeneratedFileError(f"Duplicate generated file: {path}")
    files[path] = content


def normalize_identifier(value: str, default: str = "default") -> str:
    """Normalize free-form text for Python identifiers and file stems."""
    normalized = re.sub(r"\W+", "_", value.casefold(), flags=re.UNICODE).strip("_")
    if not normalized:
        normalized = default
    if normalized[0].isdigit() or keyword.iskeyword(normalized):
        normalized = f"tag_{normalized}"
    if not normalized.isidentifier():
        return default
    return normalized
