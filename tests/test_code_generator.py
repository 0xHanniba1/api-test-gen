from unittest.mock import patch, MagicMock

import pytest

from api_test_gen.generator.code import CodeGenerator
from api_test_gen.generator.common import GenerationValidationError

SAMPLE_TESTCASES = """## POST /api/users

> Create user

| 编号 | 场景 | 输入 | 预期状态码 | 预期响应 | 优先级 |
|------|------|------|-----------|---------|--------|
| TC-001 | 正常创建用户 | {"name":"test","email":"a@b.com"} | 201 | 返回用户ID | P0 |
| TC-002 | 缺少必填字段 name | {"email":"a@b.com"} | 400 | 提示 name 必填 | P0 |
"""

MOCK_CODE_RESPONSE = '''```python
# test_create_user.py
import requests


class TestCreateUser:
    """POST /api/users"""

    def test_create_user_success(self, base_url, auth_headers):
        """TC-001: 正常创建用户"""
        resp = requests.post(
            f"{base_url}/api/users",
            json={"name": "test", "email": "a@b.com"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
```
'''

FIXED_CODE_RESPONSE = MOCK_CODE_RESPONSE.replace(
    "assert resp.status_code == 201", "assert resp.status_code == 201  # fixed"
)
SECOND_FIXED_CODE_RESPONSE = MOCK_CODE_RESPONSE.replace(
    "class TestCreateUser:", "class TestCreateUserFixed:"
)


class TestCodeGenerator:
    @patch("api_test_gen.generator.common.validate_files", return_value={})
    @patch("api_test_gen.generator.code.LlmClient")
    def test_generate_returns_file_dict(self, MockLlmClient, _mock_validate):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_CODE_RESPONSE
        MockLlmClient.return_value = mock_client

        gen = CodeGenerator(model="test-model")
        files = gen.generate(SAMPLE_TESTCASES)

        assert isinstance(files, dict)
        assert "conftest.py" in files
        assert "test_post_api_users.py" in files
        assert "API_BASE_URL" in files["conftest.py"]

    @patch("api_test_gen.generator.common.validate_files", return_value={})
    @patch("api_test_gen.generator.code.LlmClient")
    def test_generated_code_contains_class(self, MockLlmClient, _mock_validate):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_CODE_RESPONSE
        MockLlmClient.return_value = mock_client

        gen = CodeGenerator(model="test-model")
        files = gen.generate(SAMPLE_TESTCASES)

        test_files = {k: v for k, v in files.items() if k != "conftest.py"}
        assert len(test_files) > 0
        for content in test_files.values():
            assert "class Test" in content

    @patch("api_test_gen.generator.common.validate_files", return_value={})
    @patch("api_test_gen.generator.code.LlmClient")
    def test_slug_collisions_get_distinct_stable_filenames(
        self, MockLlmClient, _mock_validate
    ):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_CODE_RESPONSE
        MockLlmClient.return_value = mock_client
        second_section = (
            SAMPLE_TESTCASES.replace("POST /api/users", "POST /api_users")
            .replace("TC-001", "TC-003")
            .replace("TC-002", "TC-004")
        )

        files = CodeGenerator(model="test-model").generate(
            f"{SAMPLE_TESTCASES}\n{second_section}"
        )

        names = sorted(name for name in files if name != "conftest.py")
        assert len(names) == 2
        assert all(name.startswith("test_post_api_users_") for name in names)


class TestCodeGeneratorValidation:
    @patch("api_test_gen.generator.common.validate_files")
    @patch("api_test_gen.generator.code.LlmClient")
    def test_retries_on_validation_error(self, MockLlmClient, mock_validate):
        """Validation fails first, then passes after retry."""
        mock_client = MagicMock()
        mock_client.call.side_effect = [
            MOCK_CODE_RESPONSE,  # first generate
            FIXED_CODE_RESPONSE,  # retry
        ]
        MockLlmClient.return_value = mock_client

        # First call returns error, second returns clean
        mock_validate.side_effect = [
            {"test_post_api_users.py": "SyntaxError: line 5"},
            {},
        ]

        gen = CodeGenerator(model="test-model")
        files = gen.generate(SAMPLE_TESTCASES)

        assert isinstance(files, dict)
        assert mock_validate.call_count == 2
        assert mock_client.call.call_count == 2

    @patch("api_test_gen.generator.common.validate_files")
    @patch("api_test_gen.generator.code.LlmClient")
    def test_gives_up_after_max_retries(self, MockLlmClient, mock_validate):
        mock_client = MagicMock()
        mock_client.call.side_effect = [
            MOCK_CODE_RESPONSE,
            FIXED_CODE_RESPONSE,
            SECOND_FIXED_CODE_RESPONSE,
        ]
        MockLlmClient.return_value = mock_client

        # Always returns errors
        mock_validate.return_value = {"test_post_api_users.py": "SyntaxError: line 5"}

        gen = CodeGenerator(model="test-model")
        with pytest.raises(GenerationValidationError) as exc_info:
            gen.generate(SAMPLE_TESTCASES)

        assert "test_post_api_users.py" in exc_info.value.errors
        # initial + 2 retries = 3 validation calls
        assert mock_validate.call_count == 3

    @patch("api_test_gen.generator.common.validate_files")
    @patch("api_test_gen.generator.code.LlmClient")
    def test_no_retry_when_valid(self, MockLlmClient, mock_validate):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_CODE_RESPONSE
        MockLlmClient.return_value = mock_client

        mock_validate.return_value = {}  # no errors

        gen = CodeGenerator(model="test-model")
        files = gen.generate(SAMPLE_TESTCASES)

        assert isinstance(files, dict)
        assert mock_validate.call_count == 1  # only checked once
        assert mock_client.call.call_count == 1  # no retries
