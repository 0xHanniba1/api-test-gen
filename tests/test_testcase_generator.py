from unittest.mock import MagicMock, patch

import pytest

from api_test_agent.generator.testcase import TestCaseGenerator
from api_test_agent.generator.testcase_document import TestCaseDocumentError
from api_test_agent.parser.base import ApiEndpoint

MOCK_LLM_RESPONSE = """```json
[
  {
    "scenario": "正常创建用户",
    "input": {"name": "test", "email": "a@b.com"},
    "expected_status": 201,
    "expected_response": "返回用户ID",
    "priority": "P0"
  },
  {
    "scenario": "缺少必填字段 name",
    "input": {"email": "a@b.com"},
    "expected_status": 400,
    "expected_response": "提示 name 必填",
    "priority": "P1"
  }
]
```"""


class TestTestCaseGenerator:
    def _make_endpoint(self):
        return ApiEndpoint(
            method="POST",
            path="/api/users",
            summary="Create user",
            parameters=[],
            request_body={
                "type": "object",
                "properties": {"name": {"type": "string"}, "email": {"type": "string"}},
                "required": ["name", "email"],
            },
            responses={"201": {"description": "Created"}},
            auth_required=True,
            tags=["users"],
        )

    @patch("api_test_agent.generator.testcase.LlmClient")
    def test_generate_returns_markdown(self, MockLlmClient):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_LLM_RESPONSE
        MockLlmClient.return_value = mock_client

        gen = TestCaseGenerator(model="test-model")
        result = gen.generate([self._make_endpoint()], depth="quick")

        assert "TC-001" in result
        assert "TC-002" in result
        assert "POST /api/users" in result

    @patch("api_test_agent.generator.testcase.LlmClient")
    def test_generate_calls_llm_with_skills(self, MockLlmClient):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_LLM_RESPONSE
        MockLlmClient.return_value = mock_client

        gen = TestCaseGenerator(model="test-model")
        gen.generate([self._make_endpoint()], depth="quick")

        call_args = mock_client.call.call_args
        system_prompt = (
            call_args[1]["system"] if "system" in call_args[1] else call_args[0][0]
        )
        assert "测试" in system_prompt or "test" in system_prompt.lower()
        assert "JSON" in system_prompt

    @patch("api_test_agent.generator.testcase.LlmClient")
    def test_generate_uses_requested_start_index(self, MockLlmClient):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_LLM_RESPONSE
        MockLlmClient.return_value = mock_client

        result = TestCaseGenerator(model="test-model").generate(
            [self._make_endpoint()], start_index=12
        )

        assert "TC-012" in result
        assert "TC-013" in result

    @patch("api_test_agent.generator.testcase.LlmClient")
    def test_duplicate_endpoints_fail_before_second_llm_call(self, MockLlmClient):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_LLM_RESPONSE
        MockLlmClient.return_value = mock_client

        with pytest.raises(TestCaseDocumentError, match="Duplicate endpoint"):
            TestCaseGenerator(model="test-model").generate(
                [self._make_endpoint(), self._make_endpoint()]
            )

        mock_client.call.assert_called_once()
