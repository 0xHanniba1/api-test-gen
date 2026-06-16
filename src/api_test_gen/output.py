"""Safe filesystem output helpers for generated artifacts."""

from dataclasses import dataclass
from pathlib import Path


class OutputError(ValueError):
    """Base error for generated artifact writes."""


class UnsafeOutputPathError(OutputError):
    """Raised when a generated path would escape the output directory."""


class OutputPathConflictError(OutputError):
    """Raised when generated paths resolve to the same output file."""


@dataclass(frozen=True)
class WriteResult:
    """Summary of a generated-files write operation."""

    created: tuple[Path, ...]
    skipped: tuple[Path, ...]


def write_text(path: Path, content: str, append: bool = False) -> None:
    """Write text to a file, optionally appending after existing content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if append and path.exists():
        existing = path.read_text(encoding="utf-8")
        content = f"{existing}\n{content}"
    path.write_text(content, encoding="utf-8")


def write_generated_files(
    output_dir: Path, files: dict[str, str], append: bool = False
) -> WriteResult:
    """Write generated files below output_dir after validating every path."""
    paths = {
        relative_path: _resolve_output_path(output_dir, relative_path)
        for relative_path in files
    }
    if len(set(paths.values())) != len(paths):
        raise OutputPathConflictError("Generated paths resolve to the same output file")

    created = []
    skipped = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for relative_path, content in files.items():
        file_path = paths[relative_path]
        if append and file_path.exists():
            skipped.append(file_path)
            continue
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        created.append(file_path)

    return WriteResult(created=tuple(created), skipped=tuple(skipped))


def _resolve_output_path(output_dir: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if not relative_path or candidate.is_absolute() or ".." in candidate.parts:
        raise UnsafeOutputPathError(f"Unsafe generated path: {relative_path!r}")

    root = output_dir.resolve()
    target = (root / candidate).resolve()
    if not target.is_relative_to(root) or target == root:
        raise UnsafeOutputPathError(f"Unsafe generated path: {relative_path!r}")
    return target
