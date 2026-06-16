"""Structured test-case document models and Markdown conversion."""

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, TypeAdapter, ValidationError, field_validator

from api_test_gen.generator.common import GenerationError, extract_fenced_content
from api_test_gen.parser.base import ApiEndpoint

CASE_ID_PATTERN = re.compile(r"^TC-(\d+)$", re.IGNORECASE)
ENDPOINT_HEADING_PATTERN = re.compile(r"^##\s+([A-Za-z]+)\s+(\S+)\s*$")
TABLE_SEPARATOR_PATTERN = re.compile(r"^:?-{3,}:?$")


class TestCaseDocumentError(GenerationError):
    """Raised when generated or user-edited test-case data is invalid."""


class TestCaseDraft(BaseModel):
    """LLM-provided test-case fields before deterministic ID assignment."""

    scenario: str
    input: Any = None
    expected_status: int | str
    expected_response: str
    priority: Literal["P0", "P1", "P2"]

    @field_validator("scenario", "expected_response")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, value: Any) -> str:
        return str(value).upper()


@dataclass(frozen=True)
class TestCase:
    case_id: str
    scenario: str
    input_text: str
    expected_status: str
    expected_response: str
    priority: str


@dataclass(frozen=True)
class EndpointSection:
    method: str
    path: str
    summary: str
    cases: tuple[TestCase, ...]
    markdown: str

    @property
    def key(self) -> tuple[str, str]:
        return self.method, self.path


@dataclass(frozen=True)
class TestCaseDocument:
    sections: tuple[EndpointSection, ...]

    def section_map(self) -> dict[tuple[str, str], EndpointSection]:
        return {section.key: section for section in self.sections}


def parse_drafts(response: str) -> list[TestCaseDraft]:
    """Parse and validate the JSON array returned by the LLM."""
    payload = extract_fenced_content(response, "json")
    try:
        data = json.loads(payload)
        drafts = TypeAdapter(list[TestCaseDraft]).validate_python(data)
    except (json.JSONDecodeError, ValidationError) as error:
        raise TestCaseDocumentError(f"Invalid test-case JSON: {error}") from error
    if not drafts:
        raise TestCaseDocumentError("Test-case JSON must contain at least one case")
    return drafts


def render_endpoint_section(
    endpoint: ApiEndpoint, drafts: list[TestCaseDraft], start_index: int
) -> tuple[str, int]:
    """Assign IDs and render one endpoint section as canonical Markdown."""
    if start_index < 1:
        raise TestCaseDocumentError("Test-case numbering must start at 1 or later")
    if not drafts:
        raise TestCaseDocumentError("Endpoint section must contain at least one case")

    rows = []
    next_index = start_index
    for draft in drafts:
        case_id = f"TC-{next_index:03d}"
        next_index += 1
        rows.append(
            "| "
            + " | ".join(
                [
                    case_id,
                    _escape_cell(draft.scenario),
                    _escape_cell(_format_input(draft.input)),
                    _escape_cell(str(draft.expected_status)),
                    _escape_cell(draft.expected_response),
                    draft.priority,
                ]
            )
            + " |"
        )

    summary = endpoint.summary or endpoint.description
    lines = [
        f"## {endpoint.method} {endpoint.path}",
        "",
        f"> {summary}",
        "",
        "| 编号 | 场景 | 输入 | 预期状态码 | 预期响应 | 优先级 |",
        "|------|------|------|-----------|---------|--------|",
        *rows,
    ]
    return "\n".join(lines), next_index


def parse_testcase_document(markdown: str) -> TestCaseDocument:
    """Parse canonical or user-edited test-case Markdown into endpoint sections."""
    raw_sections = _split_endpoint_sections(markdown)
    if not raw_sections:
        raise TestCaseDocumentError("No endpoint sections found in test-case Markdown")

    sections = []
    endpoint_keys: set[tuple[str, str]] = set()
    case_ids: set[str] = set()
    for raw_section in raw_sections:
        lines = raw_section.splitlines()
        heading = ENDPOINT_HEADING_PATTERN.fullmatch(lines[0].strip())
        if heading is None:
            raise TestCaseDocumentError(f"Invalid endpoint heading: {lines[0]!r}")
        method, path = heading.groups()
        key = (method.upper(), path)
        if key in endpoint_keys:
            raise TestCaseDocumentError(
                f"Duplicate endpoint section: {key[0]} {key[1]}"
            )
        endpoint_keys.add(key)

        summary = _extract_summary(lines)
        cases = _parse_case_rows(lines)
        if not cases:
            raise TestCaseDocumentError(
                f"Endpoint section has no test cases: {key[0]} {key[1]}"
            )
        for case in cases:
            normalized_id = case.case_id.upper()
            if normalized_id in case_ids:
                raise TestCaseDocumentError(f"Duplicate test-case ID: {normalized_id}")
            case_ids.add(normalized_id)

        sections.append(
            EndpointSection(
                method=key[0],
                path=key[1],
                summary=summary,
                cases=tuple(cases),
                markdown=raw_section.strip(),
            )
        )
    return TestCaseDocument(sections=tuple(sections))


def next_case_index(markdown: str) -> int:
    """Return the next global test-case number for append mode."""
    document = parse_testcase_document(markdown)
    numbers = [
        int(CASE_ID_PATTERN.fullmatch(case.case_id).group(1))
        for section in document.sections
        for case in section.cases
    ]
    return max(numbers, default=0) + 1


def _split_endpoint_sections(markdown: str) -> list[str]:
    sections = []
    current = []
    for line in markdown.splitlines():
        if ENDPOINT_HEADING_PATTERN.fullmatch(line.strip()):
            if current:
                sections.append("\n".join(current).strip())
            current = [line]
        elif current:
            current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    return sections


def _extract_summary(lines: list[str]) -> str:
    for line in lines[1:]:
        stripped = line.strip()
        if stripped.startswith(">"):
            return stripped[1:].strip()
        if stripped.startswith("## "):
            break
    return ""


def _parse_case_rows(lines: list[str]) -> list[TestCase]:
    cases = []
    in_case_table = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = _split_markdown_row(stripped)
        if cells and cells[0] == "编号":
            in_case_table = True
            continue
        if not in_case_table:
            continue
        if not cells or all(TABLE_SEPARATOR_PATTERN.fullmatch(cell) for cell in cells):
            continue
        if len(cells) != 6:
            raise TestCaseDocumentError(f"Test-case row must have 6 columns: {line!r}")
        if not CASE_ID_PATTERN.fullmatch(cells[0]):
            raise TestCaseDocumentError(f"Invalid test-case ID: {cells[0]!r}")
        priority = cells[5].upper()
        if priority not in {"P0", "P1", "P2"}:
            raise TestCaseDocumentError(
                f"Invalid priority for {cells[0]}: {cells[5]!r}"
            )
        cases.append(
            TestCase(
                case_id=cells[0].upper(),
                scenario=cells[1],
                input_text=cells[2],
                expected_status=cells[3],
                expected_response=cells[4],
                priority=priority,
            )
        )
    return cases


def _split_markdown_row(row: str) -> list[str]:
    content = row[1:-1] if row.endswith("|") else row[1:]
    cells = []
    current = []
    escaped = False
    for char in content:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())
    return cells


def _format_input(value: Any) -> str:
    if value is None:
        return "无"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _escape_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")
