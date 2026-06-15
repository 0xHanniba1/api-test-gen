from unittest.mock import MagicMock, patch

import pytest

from api_test_agent.parser.base import ApiEndpoint
from api_test_agent.pipeline import (
    DocumentParseError,
    generate_code,
    generate_testcases,
    parse_document,
)


def _endpoint() -> ApiEndpoint:
    return ApiEndpoint(
        method="GET",
        path="/pets",
        summary="List pets",
        parameters=[],
        request_body=None,
        responses={},
        auth_required=False,
        tags=["pets"],
    )


@patch("api_test_agent.pipeline.parse_markdown")
def test_parse_document_forwards_model_to_markdown(mock_parse, tmp_path):
    doc = tmp_path / "api.md"
    doc.write_text("# API", encoding="utf-8")
    mock_parse.return_value = [_endpoint()]

    endpoints = parse_document(doc, fmt="markdown", model="custom-model")

    assert endpoints == [_endpoint()]
    mock_parse.assert_called_once_with(doc, model="custom-model")


@patch("api_test_agent.pipeline.CodeGenerator")
def test_generate_code_selects_flat_generator(MockGenerator):
    generator = MagicMock()
    generator.generate.return_value = {"test_pets.py": "# test"}
    MockGenerator.return_value = generator

    files = generate_code("## GET /pets", arch="flat", model="test-model")

    assert files == {"test_pets.py": "# test"}
    MockGenerator.assert_called_once_with(model="test-model")


@patch("api_test_agent.pipeline.TestCaseGenerator")
def test_generate_testcases_forwards_start_index(MockGenerator):
    generator = MagicMock()
    generator.generate.return_value = "## GET /pets"
    MockGenerator.return_value = generator

    result = generate_testcases(
        [_endpoint()], depth="full", model="test-model", start_index=8
    )

    assert result == "## GET /pets"
    MockGenerator.assert_called_once_with(model="test-model")
    generator.generate.assert_called_once_with(
        [_endpoint()], depth="full", start_index=8
    )


def test_layered_generation_requires_endpoints():
    with pytest.raises(ValueError, match="endpoints are required"):
        generate_code("## GET /pets", arch="layered")


def test_parse_document_wraps_parser_errors(tmp_path):
    document = tmp_path / "broken.yaml"
    document.write_text("openapi: 3.0.0\npaths: [invalid", encoding="utf-8")

    with pytest.raises(DocumentParseError, match="Failed to parse"):
        parse_document(document, fmt="swagger")
