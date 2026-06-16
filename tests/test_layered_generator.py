from unittest.mock import MagicMock, patch

import pytest

from api_test_gen.generator.layered import LayeredCodeGenerator
from api_test_gen.generator.testcase_document import TestCaseDocumentError
from api_test_gen.parser.base import ApiEndpoint


def _ep(method, path, tags):
    return ApiEndpoint(
        method=method,
        path=path,
        summary=f"{method} {path}",
        parameters=[],
        request_body=None,
        responses={},
        auth_required=False,
        tags=tags,
    )


class TestGroupByTag:
    def test_groups_endpoints_by_first_tag(self):
        endpoints = [
            _ep("POST", "/users", ["users"]),
            _ep("GET", "/users/{id}", ["users"]),
            _ep("GET", "/pets", ["pets"]),
        ]
        gen = LayeredCodeGenerator.__new__(LayeredCodeGenerator)
        groups = gen._group_by_tag(endpoints)
        assert set(groups.keys()) == {"users", "pets"}
        assert len(groups["users"]) == 2
        assert len(groups["pets"]) == 1

    def test_untagged_endpoints_use_default(self):
        endpoints = [_ep("GET", "/health", [])]
        gen = LayeredCodeGenerator.__new__(LayeredCodeGenerator)
        groups = gen._group_by_tag(endpoints)
        assert "default" in groups

    def test_normalizes_tag_for_python_and_file_paths(self):
        endpoints = [_ep("GET", "/health", ["../../Admin API"])]
        gen = LayeredCodeGenerator.__new__(LayeredCodeGenerator)
        groups = gen._group_by_tag(endpoints)
        assert set(groups) == {"admin_api"}


class TestTemplateGeneration:
    def test_generate_config(self):
        gen = LayeredCodeGenerator.__new__(LayeredCodeGenerator)
        config = gen._render_config()
        assert "API_BASE_URL" in config
        assert "API_TOKEN" in config
        assert "os.getenv" in config

    def test_generate_client(self):
        gen = LayeredCodeGenerator.__new__(LayeredCodeGenerator)
        client = gen._render_client()
        assert "class HttpClient" in client
        assert "def get(" in client
        assert "def post(" in client
        assert "def put(" in client
        assert "def delete(" in client

    def test_generate_requirements(self):
        gen = LayeredCodeGenerator.__new__(LayeredCodeGenerator)
        req = gen._render_requirements()
        assert "requests" in req
        assert "pytest" in req
        assert "pyyaml" in req

    def test_generate_conftest(self):
        tag_names = ["users", "pets"]
        gen = LayeredCodeGenerator.__new__(LayeredCodeGenerator)
        conftest = gen._render_conftest(tag_names)
        assert "HttpClient" in conftest
        assert "UsersApi" in conftest
        assert "PetsApi" in conftest
        assert "def users_api" in conftest
        assert "def pets_api" in conftest

    def test_generate_jenkinsfile(self):
        gen = LayeredCodeGenerator.__new__(LayeredCodeGenerator)
        jf = gen._render_jenkinsfile()
        assert "pipeline {" in jf
        assert "credentials('api-token')" in jf
        assert "pytest tests/" in jf
        assert "--junitxml=" in jf
        assert "junit 'reports/*.xml'" in jf
        assert "params.ENV" in jf


MOCK_API_RESPONSE = """```python
# users_api.py
from base.client import HttpClient


class UsersApi:
    def __init__(self, client: HttpClient):
        self.client = client

    def create_user(self, body: dict):
        return self.client.post("/api/users", json=body)

    def get_user(self, user_id: int):
        return self.client.get(f"/api/users/{user_id}")
```"""

MOCK_DATA_RESPONSE = """```yaml
# users.yaml
create_user:
  valid:
    body:
      name: "test"
      email: "a@b.com"
    expected_status: 201
  missing_name:
    body:
      email: "a@b.com"
    expected_status: 400
```"""

MOCK_SERVICES_RESPONSE = """```python
# user_flow.py
from api.users_api import UsersApi


class UserFlow:
    def __init__(self, api: UsersApi):
        self.api = api

    def create_and_get(self, body: dict):
        resp = self.api.create_user(body)
        user_id = resp.json()["id"]
        return self.api.get_user(user_id)
```"""

MOCK_TESTS_RESPONSE = '''```python
# test_users.py
import yaml
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"


def load_data(resource: str) -> dict:
    with open(DATA_DIR / f"{resource}.yaml") as f:
        return yaml.safe_load(f)


class TestCreateUser:
    """POST /api/users"""
    data = load_data("users")["create_user"]

    def test_success(self, users_api):
        """TC-001: 正常创建用户"""
        d = self.data["valid"]
        resp = users_api.create_user(d["body"])
        assert resp.status_code == d["expected_status"]
```'''

FIXED_API_RESPONSE = MOCK_API_RESPONSE.replace(
    "class UsersApi:", "class UsersApi:  # fixed"
)


class TestApiLayerGeneration:
    @patch("api_test_gen.generator.layered.LlmClient")
    def test_generate_api_layer(self, MockLlmClient):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_API_RESPONSE
        MockLlmClient.return_value = mock_client

        endpoints = [
            _ep("POST", "/api/users", ["users"]),
            _ep("GET", "/api/users/{id}", ["users"]),
        ]
        gen = LayeredCodeGenerator(model="test")
        result = gen._generate_api_layer("users", endpoints)

        assert "users_api.py" in result[0]
        assert "class UsersApi" in result[1]
        mock_client.call.assert_called_once()


class TestDataLayerGeneration:
    @patch("api_test_gen.generator.layered.LlmClient")
    def test_generate_data_layer(self, MockLlmClient):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_DATA_RESPONSE
        MockLlmClient.return_value = mock_client

        testcases_section = "## POST /api/users\n| TC-001 | test | ... |"
        gen = LayeredCodeGenerator(model="test")
        result = gen._generate_data_layer("users", testcases_section)

        assert "users.yaml" in result[0]
        assert "create_user" in result[1]
        mock_client.call.assert_called_once()


class TestServicesLayerGeneration:
    @patch("api_test_gen.generator.layered.LlmClient")
    def test_generate_services_layer(self, MockLlmClient):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_SERVICES_RESPONSE
        MockLlmClient.return_value = mock_client

        api_code = "class UsersApi:\n    def create_user(self, body): ..."
        endpoints = [
            _ep("POST", "/api/users", ["users"]),
            _ep("GET", "/api/users/{id}", ["users"]),
        ]
        gen = LayeredCodeGenerator(model="test")
        result = gen._generate_services_layer("users", endpoints, api_code)

        assert result[0] == "users_flow.py"
        assert "class UserFlow" in result[1]
        mock_client.call.assert_called_once()

    @patch("api_test_gen.generator.layered.LlmClient")
    def test_service_filename_does_not_depend_on_llm_comment(self, MockLlmClient):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_SERVICES_RESPONSE.replace(
            "# user_flow.py", "# ../../escape.py"
        )
        MockLlmClient.return_value = mock_client

        gen = LayeredCodeGenerator(model="test")
        filename, _ = gen._generate_services_layer(
            "users", [_ep("GET", "/api/users", ["users"])], "class UsersApi: ..."
        )

        assert filename == "users_flow.py"


class TestTestsLayerGeneration:
    @patch("api_test_gen.generator.layered.LlmClient")
    def test_generate_tests_layer(self, MockLlmClient):
        mock_client = MagicMock()
        mock_client.call.return_value = MOCK_TESTS_RESPONSE
        MockLlmClient.return_value = mock_client

        testcases_section = "## POST /api/users\n| TC-001 | test | ... |"
        api_code = "class UsersApi:\n    def create_user(self, body): ..."
        data_content = "create_user:\n  valid:\n    body: {}\n    expected_status: 201"
        gen = LayeredCodeGenerator(model="test")
        result = gen._generate_tests_layer(
            "users", testcases_section, api_code, data_content
        )

        assert "test_users.py" in result[0]
        assert "class TestCreateUser" in result[1]
        assert "load_data" in result[1]
        mock_client.call.assert_called_once()


SAMPLE_TESTCASES = """## POST /api/users

> Create user

| 编号 | 场景 | 输入 | 预期状态码 | 预期响应 | 优先级 |
|------|------|------|-----------|---------|--------|
| TC-001 | 正常创建用户 | {} | 201 | ok | P0 |

## GET /api/users/{id}

> Get user by ID

| 编号 | 场景 | 输入 | 预期状态码 | 预期响应 | 优先级 |
|------|------|------|-----------|---------|--------|
| TC-002 | 正常查询 | id=1 | 200 | ok | P0 |

## GET /api/pets

> List pets

| 编号 | 场景 | 输入 | 预期状态码 | 预期响应 | 优先级 |
|------|------|------|-----------|---------|--------|
| TC-003 | 正常查询 | {} | 200 | ok | P0 |
"""


class TestSectionExtraction:
    def test_extract_sections_for_tag(self):
        endpoints = [
            _ep("POST", "/api/users", ["users"]),
            _ep("GET", "/api/users/{id}", ["users"]),
        ]
        gen = LayeredCodeGenerator.__new__(LayeredCodeGenerator)
        section = gen._extract_sections_for_endpoints(SAMPLE_TESTCASES, endpoints)
        assert "POST /api/users" in section
        assert "GET /api/users/{id}" in section
        assert "GET /api/pets" not in section

    def test_missing_section_fails_explicitly(self):
        endpoints = [_ep("DELETE", "/api/users/{id}", ["users"])]
        gen = LayeredCodeGenerator.__new__(LayeredCodeGenerator)

        with pytest.raises(TestCaseDocumentError, match="Missing test-case section"):
            gen._extract_sections_for_endpoints(SAMPLE_TESTCASES, endpoints)


MOCK_PETS_API_RESPONSE = """```python
# pets_api.py
from base.client import HttpClient


class PetsApi:
    def __init__(self, client: HttpClient):
        self.client = client

    def list_pets(self):
        return self.client.get("/api/pets")
```"""

MOCK_PETS_DATA_RESPONSE = """```yaml
# pets.yaml
list_pets:
  valid:
    expected_status: 200
```"""

MOCK_PETS_SERVICES_RESPONSE = """```python
# pet_flow.py
from api.pets_api import PetsApi


class PetFlow:
    def __init__(self, api: PetsApi):
        self.api = api
```"""

MOCK_PETS_TESTS_RESPONSE = """```python
# test_pets.py
class TestListPets:
    def test_success(self, pets_api):
        resp = pets_api.list_pets()
        assert resp.status_code == 200
```"""


class TestLayeredGenerate:
    @patch("api_test_gen.generator.common.validate_files", return_value={})
    @patch("api_test_gen.generator.layered.LlmClient")
    def test_generate_returns_all_layers(self, MockLlmClient, _mock_validate):
        mock_client = MagicMock()
        mock_client.call.side_effect = [
            MOCK_API_RESPONSE,  # api layer for users
            MOCK_DATA_RESPONSE,  # data layer for users
            MOCK_SERVICES_RESPONSE,  # services layer for users
            MOCK_TESTS_RESPONSE,  # tests layer for users
        ]
        MockLlmClient.return_value = mock_client

        endpoints = [
            _ep("POST", "/api/users", ["users"]),
            _ep("GET", "/api/users/{id}", ["users"]),
        ]
        gen = LayeredCodeGenerator(model="test")
        files = gen.generate(SAMPLE_TESTCASES, endpoints)

        # Static files
        assert "base/__init__.py" in files
        assert "base/config.py" in files
        assert "base/client.py" in files
        assert "requirements.txt" in files
        assert "Jenkinsfile" in files

        # Dynamic files
        assert "api/__init__.py" in files
        assert any("_api.py" in k for k in files)
        assert any(".yaml" in k for k in files)
        assert "services/__init__.py" in files
        assert any("_flow.py" in k for k in files)
        assert "tests/__init__.py" in files
        assert "tests/conftest.py" in files
        assert any("test_" in k for k in files)

        assert mock_client.call.call_count == 4

    @patch("api_test_gen.generator.common.validate_files", return_value={})
    @patch("api_test_gen.generator.layered.LlmClient")
    def test_generate_multi_tag(self, MockLlmClient, _mock_validate):
        """Test with 2 tags: users + pets — should produce 8 LLM calls."""
        mock_client = MagicMock()
        mock_client.call.side_effect = [
            # pets tag (alphabetically first)
            MOCK_PETS_API_RESPONSE,
            MOCK_PETS_DATA_RESPONSE,
            MOCK_PETS_SERVICES_RESPONSE,
            MOCK_PETS_TESTS_RESPONSE,
            # users tag
            MOCK_API_RESPONSE,
            MOCK_DATA_RESPONSE,
            MOCK_SERVICES_RESPONSE,
            MOCK_TESTS_RESPONSE,
        ]
        MockLlmClient.return_value = mock_client

        endpoints = [
            _ep("POST", "/api/users", ["users"]),
            _ep("GET", "/api/users/{id}", ["users"]),
            _ep("GET", "/api/pets", ["pets"]),
        ]
        gen = LayeredCodeGenerator(model="test")
        files = gen.generate(SAMPLE_TESTCASES, endpoints)

        # Both tags should have api, data, services, tests files
        assert "api/users_api.py" in files
        assert "api/pets_api.py" in files
        assert "data/users.yaml" in files
        assert "data/pets.yaml" in files
        assert "services/users_flow.py" in files
        assert "services/pets_flow.py" in files
        assert "tests/test_users.py" in files
        assert "tests/test_pets.py" in files

        # Conftest should have fixtures for both
        conftest = files["tests/conftest.py"]
        assert "UsersApi" in conftest
        assert "PetsApi" in conftest

        assert mock_client.call.call_count == 8


class TestLayeredValidation:
    @patch("api_test_gen.generator.common.validate_files")
    @patch("api_test_gen.generator.layered.LlmClient")
    def test_retries_on_validation_error(self, MockLlmClient, mock_validate):
        mock_client = MagicMock()
        mock_client.call.side_effect = [
            MOCK_API_RESPONSE,  # api layer
            MOCK_DATA_RESPONSE,  # data layer
            MOCK_SERVICES_RESPONSE,  # services layer
            MOCK_TESTS_RESPONSE,  # tests layer
            FIXED_API_RESPONSE,  # retry: fixed api
        ]
        MockLlmClient.return_value = mock_client

        mock_validate.side_effect = [
            {"api/users_api.py": "SyntaxError: line 3"},
            {},
        ]

        endpoints = [
            _ep("POST", "/api/users", ["users"]),
            _ep("GET", "/api/users/{id}", ["users"]),
        ]
        gen = LayeredCodeGenerator(model="test")
        files = gen.generate(SAMPLE_TESTCASES, endpoints)

        assert isinstance(files, dict)
        assert mock_validate.call_count == 2
        assert mock_client.call.call_count == 5  # 4 layers + 1 retry

    @patch("api_test_gen.generator.common.validate_files")
    @patch("api_test_gen.generator.layered.LlmClient")
    def test_no_retry_when_valid(self, MockLlmClient, mock_validate):
        mock_client = MagicMock()
        mock_client.call.side_effect = [
            MOCK_API_RESPONSE,
            MOCK_DATA_RESPONSE,
            MOCK_SERVICES_RESPONSE,
            MOCK_TESTS_RESPONSE,
        ]
        MockLlmClient.return_value = mock_client

        mock_validate.return_value = {}

        endpoints = [
            _ep("POST", "/api/users", ["users"]),
            _ep("GET", "/api/users/{id}", ["users"]),
        ]
        gen = LayeredCodeGenerator(model="test")
        gen.generate(SAMPLE_TESTCASES, endpoints)

        assert mock_validate.call_count == 1
        assert mock_client.call.call_count == 4
