import pytest

from api_test_agent.generator.testcase_document import (
    TestCaseDocumentError,
    next_case_index,
    parse_drafts,
    parse_testcase_document,
    render_endpoint_section,
)
from api_test_agent.parser.base import ApiEndpoint


def _endpoint(method: str = "POST", path: str = "/users") -> ApiEndpoint:
    return ApiEndpoint(method=method, path=path, summary="Create user")


def test_parse_drafts_accepts_fenced_json():
    drafts = parse_drafts(
        """```json
[
  {
    "scenario": "valid user",
    "input": {"name": "A"},
    "expected_status": 201,
    "expected_response": "created",
    "priority": "p0"
  }
]
```"""
    )

    assert drafts[0].priority == "P0"
    assert drafts[0].input == {"name": "A"}


@pytest.mark.parametrize("response", ["not json", "[]", "{}"])
def test_parse_drafts_rejects_invalid_payload(response):
    with pytest.raises(TestCaseDocumentError):
        parse_drafts(response)


def test_render_and_parse_round_trip_with_escaped_cells():
    drafts = parse_drafts(
        """[
  {
    "scenario": "name contains | and backslash \\\\",
    "input": {"path": "C:\\\\tmp", "value": "a|b"},
    "expected_status": "2XX",
    "expected_response": "line one\\nline two",
    "priority": "P1"
  }
]"""
    )

    markdown, next_index = render_endpoint_section(_endpoint(), drafts, 7)
    document = parse_testcase_document(markdown)
    case = document.sections[0].cases[0]

    assert next_index == 8
    assert case.case_id == "TC-007"
    assert case.scenario == "name contains | and backslash \\"
    assert case.input_text == '{"path":"C:\\\\tmp","value":"a|b"}'
    assert case.expected_response == "line one<br>line two"


def test_parse_document_rejects_duplicate_endpoint_and_case_id():
    markdown, _ = render_endpoint_section(
        _endpoint(),
        parse_drafts(
            '[{"scenario":"ok","input":null,"expected_status":201,'
            '"expected_response":"ok","priority":"P0"}]'
        ),
        1,
    )

    with pytest.raises(TestCaseDocumentError, match="Duplicate endpoint"):
        parse_testcase_document(f"{markdown}\n\n{markdown}")

    second, _ = render_endpoint_section(
        _endpoint("GET", "/users"),
        parse_drafts(
            '[{"scenario":"ok","input":null,"expected_status":200,'
            '"expected_response":"ok","priority":"P0"}]'
        ),
        1,
    )
    with pytest.raises(TestCaseDocumentError, match="Duplicate test-case ID"):
        parse_testcase_document(f"{markdown}\n\n{second}")


def test_parse_document_rejects_malformed_case_row():
    markdown = """## GET /users

| 编号 | 场景 | 输入 | 预期状态码 | 预期响应 | 优先级 |
|------|------|------|-----------|---------|--------|
| invalid | ok | 无 | 200 | ok | P0 |
"""

    with pytest.raises(TestCaseDocumentError, match="Invalid test-case ID"):
        parse_testcase_document(markdown)


def test_next_case_index_uses_global_maximum():
    first, _ = render_endpoint_section(
        _endpoint(),
        parse_drafts(
            '[{"scenario":"ok","input":null,"expected_status":201,'
            '"expected_response":"ok","priority":"P0"}]'
        ),
        4,
    )
    second, _ = render_endpoint_section(
        _endpoint("GET", "/users/{id}"),
        parse_drafts(
            '[{"scenario":"ok","input":{"id":1},"expected_status":200,'
            '"expected_response":"ok","priority":"P0"}]'
        ),
        9,
    )

    assert next_case_index(f"{first}\n\n{second}") == 10


def test_render_rejects_invalid_start_index():
    drafts = parse_drafts(
        '[{"scenario":"ok","input":null,"expected_status":200,'
        '"expected_response":"ok","priority":"P0"}]'
    )

    with pytest.raises(TestCaseDocumentError, match="start at 1"):
        render_endpoint_section(_endpoint(), drafts, 0)
