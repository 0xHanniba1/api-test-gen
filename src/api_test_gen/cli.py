"""CLI entry point for api-test-gen."""

from pathlib import Path

import click

from api_test_gen.generator.common import GenerationError
from api_test_gen.generator.testcase_document import (
    next_case_index,
    parse_testcase_document,
)
from api_test_gen.output import (
    OutputError,
    WriteResult,
    write_generated_files,
    write_text,
)
from api_test_gen.parser.base import ApiEndpoint
from api_test_gen.pipeline import (
    DocumentParseError,
    filter_endpoints,
    generate_code,
    generate_testcases,
    parse_document,
)


@click.group()
def main():
    """Generate test cases and automation code from API docs."""


@main.command()
@click.argument("doc_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output",
    required=True,
    type=click.Path(path_type=Path),
    help="Output file path for test cases Markdown.",
)
@click.option(
    "--depth",
    default="quick",
    type=click.Choice(["quick", "full"]),
    help="Test depth level.",
)
@click.option("--model", default=None, help="LLM model to use.")
@click.option(
    "--format",
    "fmt",
    default="auto",
    type=click.Choice(["auto", "swagger", "postman", "markdown"]),
    help="Document format.",
)
@click.option(
    "--filter",
    "filters",
    multiple=True,
    help="Filter endpoints by pattern, e.g. 'POST /pets' or '/pets/*'.",
)
@click.option(
    "--append",
    "append_mode",
    is_flag=True,
    default=False,
    help="Append to existing file instead of overwriting.",
)
def gen_cases(
    doc_path: Path,
    output: Path,
    depth: str,
    model: str | None,
    fmt: str,
    filters: tuple[str, ...],
    append_mode: bool,
):
    """Generate a test-case document from API documentation."""
    endpoints = _load_endpoints(doc_path, fmt, model, filters)
    click.echo(f"Generating test cases (depth: {depth})...")
    appended = append_mode and output.exists()
    start_index = _append_start_index(output, append_mode, endpoints)
    testcases = _generate_testcases(endpoints, depth, model, start_index)
    write_text(output, testcases, append=append_mode)
    action = "appended to" if appended else "saved to"
    click.echo(f"Test cases {action} {output}")


@main.command()
@click.argument("cases_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output",
    required=True,
    type=click.Path(path_type=Path),
    help="Output directory for generated code.",
)
@click.option("--model", default=None, help="LLM model to use.")
@click.option(
    "--append",
    "append_mode",
    is_flag=True,
    default=False,
    help="Skip existing files instead of overwriting.",
)
@click.option(
    "--arch",
    default="flat",
    type=click.Choice(["flat", "layered"]),
    help="Code architecture style.",
)
@click.option(
    "--doc",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="API doc file (required for --arch layered).",
)
@click.option(
    "--format",
    "doc_fmt",
    default="auto",
    type=click.Choice(["auto", "swagger", "postman", "markdown"]),
    help="Document format (used with --doc).",
)
def gen_code(
    cases_path: Path,
    output: Path,
    model: str | None,
    append_mode: bool,
    arch: str,
    doc: Path | None,
    doc_fmt: str,
):
    """Generate pytest and requests code from a test-case document."""
    click.echo(f"Reading test cases from {cases_path}...")
    testcases = cases_path.read_text(encoding="utf-8")
    endpoints = _load_layered_endpoints(arch, doc, doc_fmt, model)
    files = _generate_code(testcases, arch, model, endpoints)
    result = _write_code(output, files, append_mode)
    click.echo(f"Generated {len(result.created)} files in {output}")


@main.command()
@click.argument("doc_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output",
    required=True,
    type=click.Path(path_type=Path),
    help="Output directory for all generated files.",
)
@click.option(
    "--depth",
    default="quick",
    type=click.Choice(["quick", "full"]),
    help="Test depth level.",
)
@click.option("--model", default=None, help="LLM model to use.")
@click.option(
    "--format",
    "fmt",
    default="auto",
    type=click.Choice(["auto", "swagger", "postman", "markdown"]),
    help="Document format.",
)
@click.option(
    "--filter",
    "filters",
    multiple=True,
    help="Filter endpoints by pattern, e.g. 'POST /pets' or '/pets/*'.",
)
@click.option(
    "--append",
    "append_mode",
    is_flag=True,
    default=False,
    help="Append test cases and skip existing code files.",
)
@click.option(
    "--arch",
    default="flat",
    type=click.Choice(["flat", "layered"]),
    help="Code architecture style.",
)
def run(
    doc_path: Path,
    output: Path,
    depth: str,
    model: str | None,
    fmt: str,
    filters: tuple[str, ...],
    append_mode: bool,
    arch: str,
):
    """Run the full parse, test-case, and code generation pipeline."""
    endpoints = _load_endpoints(doc_path, fmt, model, filters)

    click.echo(f"Generating test cases (depth: {depth})...")
    cases_path = output / "testcases.md"
    appended = append_mode and cases_path.exists()
    start_index = _append_start_index(cases_path, append_mode, endpoints)
    testcases = _generate_testcases(endpoints, depth, model, start_index)
    write_text(cases_path, testcases, append=append_mode)
    action = "appended to" if appended else "saved to"
    click.echo(f"  Test cases {action} {cases_path}")

    files = _generate_code(testcases, arch, model, endpoints)
    result = _write_code(output, files, append_mode)
    click.echo(f"Done! Generated {len(result.created) + 1} files in {output}")


def _load_endpoints(
    doc_path: Path,
    fmt: str,
    model: str | None,
    filters: tuple[str, ...] = (),
) -> list[ApiEndpoint]:
    click.echo(f"Parsing {doc_path} (format: {fmt})...")
    try:
        parsed = parse_document(doc_path, fmt, model=model)
    except DocumentParseError as error:
        raise click.ClickException(str(error)) from error
    endpoints = filter_endpoints(parsed, filters)
    click.echo(f"Found {len(endpoints)} endpoints.")
    return endpoints


def _load_layered_endpoints(
    arch: str, doc: Path | None, doc_fmt: str, model: str | None
) -> list[ApiEndpoint] | None:
    if arch == "flat":
        return None
    if doc is None:
        raise click.UsageError("--doc is required when using --arch layered")
    return _load_endpoints(doc, doc_fmt, model)


def _generate_code(
    testcases: str,
    arch: str,
    model: str | None,
    endpoints: list[ApiEndpoint] | None,
) -> dict[str, str]:
    label = "layered code" if arch == "layered" else "code"
    click.echo(f"Generating {label}...")
    try:
        return generate_code(testcases, arch=arch, model=model, endpoints=endpoints)
    except GenerationError as error:
        raise click.ClickException(str(error)) from error


def _generate_testcases(
    endpoints: list[ApiEndpoint],
    depth: str,
    model: str | None,
    start_index: int,
) -> str:
    try:
        return generate_testcases(
            endpoints, depth=depth, model=model, start_index=start_index
        )
    except GenerationError as error:
        raise click.ClickException(str(error)) from error


def _append_start_index(
    output: Path, append_mode: bool, endpoints: list[ApiEndpoint]
) -> int:
    if not append_mode or not output.exists():
        return 1

    existing = output.read_text(encoding="utf-8")
    if not existing.strip():
        return 1

    try:
        document = parse_testcase_document(existing)
        existing_keys = set(document.section_map())
        conflicts = [
            f"{endpoint.method} {endpoint.path}"
            for endpoint in endpoints
            if (endpoint.method, endpoint.path) in existing_keys
        ]
        if conflicts:
            joined = ", ".join(conflicts)
            raise click.ClickException(
                f"Cannot append duplicate endpoint sections: {joined}"
            )
        return next_case_index(existing)
    except GenerationError as error:
        raise click.ClickException(
            f"Cannot append to invalid test-case document: {error}"
        ) from error


def _write_code(output: Path, files: dict[str, str], append_mode: bool) -> WriteResult:
    try:
        result = write_generated_files(output, files, append=append_mode)
    except OutputError as error:
        raise click.ClickException(str(error)) from error

    for file_path in result.created:
        click.echo(f"  Created {file_path}")
    for file_path in result.skipped:
        click.echo(f"  Skipped {file_path} (already exists)")
    return result
