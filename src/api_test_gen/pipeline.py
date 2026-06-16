"""Application services for parsing API docs and generating artifacts."""

import fnmatch
from pathlib import Path

import yaml
from pydantic import ValidationError

from api_test_gen.generator.code import CodeGenerator
from api_test_gen.generator.layered import LayeredCodeGenerator
from api_test_gen.generator.testcase import TestCaseGenerator
from api_test_gen.parser.base import ApiEndpoint
from api_test_gen.parser.detect import detect_format
from api_test_gen.parser.markdown import parse_markdown
from api_test_gen.parser.postman import parse_postman
from api_test_gen.parser.swagger import parse_openapi


class DocumentParseError(ValueError):
    """Raised when an API document cannot be normalized."""


def parse_document(
    file_path: Path, fmt: str = "auto", model: str | None = None
) -> list[ApiEndpoint]:
    """Parse an API document into the common endpoint model."""
    try:
        resolved_format = detect_format(file_path) if fmt == "auto" else fmt

        if resolved_format == "swagger":
            return parse_openapi(file_path)
        if resolved_format == "postman":
            return parse_postman(file_path)
        if resolved_format == "markdown":
            return parse_markdown(file_path, model=model)
        raise ValueError(f"Unsupported document format: {resolved_format}")
    except (ValueError, yaml.YAMLError, ValidationError) as error:
        raise DocumentParseError(f"Failed to parse {file_path}: {error}") from error


def filter_endpoints(
    endpoints: list[ApiEndpoint], patterns: tuple[str, ...]
) -> list[ApiEndpoint]:
    """Filter endpoints by method and path glob patterns."""
    if not patterns:
        return endpoints

    filtered = []
    for endpoint in endpoints:
        if any(_matches_pattern(endpoint, pattern) for pattern in patterns):
            filtered.append(endpoint)
    return filtered


def generate_testcases(
    endpoints: list[ApiEndpoint],
    depth: str = "quick",
    model: str | None = None,
    start_index: int = 1,
) -> str:
    """Generate a Markdown test-case document."""
    return TestCaseGenerator(model=model).generate(
        endpoints, depth=depth, start_index=start_index
    )


def generate_code(
    testcases: str,
    arch: str = "flat",
    model: str | None = None,
    endpoints: list[ApiEndpoint] | None = None,
) -> dict[str, str]:
    """Generate test code using the selected architecture."""
    if arch == "flat":
        return CodeGenerator(model=model).generate(testcases)
    if arch == "layered":
        if endpoints is None:
            raise ValueError("endpoints are required for layered generation")
        return LayeredCodeGenerator(model=model).generate(testcases, endpoints)
    raise ValueError(f"Unsupported code architecture: {arch}")


def _matches_pattern(endpoint: ApiEndpoint, pattern: str) -> bool:
    parts = pattern.split(" ", 1)
    if len(parts) == 1:
        return fnmatch.fnmatch(endpoint.path, pattern)

    method_pattern, path_pattern = parts
    return fnmatch.fnmatch(endpoint.method, method_pattern.upper()) and fnmatch.fnmatch(
        endpoint.path, path_pattern
    )
