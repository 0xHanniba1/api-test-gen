from pathlib import Path
from unittest.mock import patch, MagicMock
import json
from api_test_gen.parser.markdown import parse_markdown
from api_test_gen.parser.base import ApiEndpoint

FIXTURES = Path(__file__).parent / "fixtures"

MOCK_LLM_RESPONSE = json.dumps([
    {
        "method": "POST",
        "path": "/api/users",
        "summary": "Create a new user",
        "parameters": [],
        "request_body": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name", "email"],
        },
        "responses": {"201": {"description": "Created"}},
        "auth_required": False,
        "tags": ["users"],
        "content_type": "application/json",
    },
    {
        "method": "GET",
        "path": "/api/users/{id}",
        "summary": "Get user by ID",
        "parameters": [
            {"name": "id", "location": "path", "required": True, "param_type": "integer"}
        ],
        "request_body": None,
        "responses": {"200": {"description": "OK"}},
        "auth_required": False,
        "tags": ["users"],
        "content_type": "application/json",
    },
])


class TestMarkdownParser:
    @patch("api_test_gen.parser.markdown.LlmClient")
    def test_parse_returns_endpoints(self, MockLlmClient):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_LLM_RESPONSE
        MockLlmClient.return_value = mock_client

        endpoints = parse_markdown(FIXTURES / "sample-api.md")
        assert len(endpoints) == 2
        assert all(isinstance(ep, ApiEndpoint) for ep in endpoints)

    @patch("api_test_gen.parser.markdown.LlmClient")
    def test_parse_extracts_correct_data(self, MockLlmClient):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_LLM_RESPONSE
        MockLlmClient.return_value = mock_client

        endpoints = parse_markdown(FIXTURES / "sample-api.md")
        post_ep = [e for e in endpoints if e.method == "POST"][0]
        assert post_ep.path == "/api/users"
        assert post_ep.request_body is not None
