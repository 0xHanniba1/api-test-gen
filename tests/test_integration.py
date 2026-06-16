"""End-to-end integration tests with mocked LLM calls."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from api_test_gen.cli import main
from api_test_gen.generator.layered import LayeredCodeGenerator
from api_test_gen.parser.base import ApiEndpoint

FIXTURES = Path(__file__).parent / "fixtures"

# Each mock represents LLM output for one endpoint (petstore has 3 endpoints)
MOCK_TC_GET_PETS = """```json
[
  {"scenario":"正常获取宠物列表","input":{"limit":10},"expected_status":200,"expected_response":"返回宠物数组","priority":"P0"},
  {"scenario":"不传参数","input":null,"expected_status":200,"expected_response":"返回默认列表","priority":"P1"}
]
```"""

MOCK_TC_POST_PETS = """```json
[
  {"scenario":"正常创建宠物","input":{"name":"Fido"},"expected_status":201,"expected_response":"返回宠物ID","priority":"P0"},
  {"scenario":"缺少 name","input":{},"expected_status":400,"expected_response":"提示 name 必填","priority":"P1"}
]
```"""

MOCK_TC_GET_PET_BY_ID = """```json
[
  {"scenario":"正常获取宠物详情","input":{"petId":1},"expected_status":200,"expected_response":"返回宠物详情","priority":"P0"},
  {"scenario":"宠物不存在","input":{"petId":9999},"expected_status":404,"expected_response":"提示宠物不存在","priority":"P1"}
]
```"""

MOCK_TEST_CODE_1 = '''```python
# test_list_pets.py
import requests

class TestListPets:
    """GET /pets"""
    def test_list_pets_success(self, base_url, auth_headers):
        """TC-001: 正常获取宠物列表"""
        resp = requests.get(f"{base_url}/pets", params={"limit": 10}, headers=auth_headers)
        assert resp.status_code == 200
```'''

MOCK_TEST_CODE_2 = '''```python
# test_create_pet.py
import requests

class TestCreatePet:
    """POST /pets"""
    def test_create_pet_success(self, base_url, auth_headers):
        """TC-003: 正常创建宠物"""
        resp = requests.post(f"{base_url}/pets", json={"name": "Fido"}, headers=auth_headers)
        assert resp.status_code == 201
```'''

MOCK_TEST_CODE_3 = '''```python
# test_show_pet.py
import requests

class TestShowPet:
    """GET /pets/{petId}"""
    def test_show_pet_success(self, base_url, auth_headers):
        """TC-005: 正常获取宠物详情"""
        resp = requests.get(f"{base_url}/pets/1", headers=auth_headers)
        assert resp.status_code == 200
```'''


class TestEndToEnd:
    @patch("api_test_gen.generator.code.LlmClient")
    @patch("api_test_gen.generator.testcase.LlmClient")
    def test_full_pipeline_petstore(self, MockTCLlm, MockCodeLlm, tmp_path):
        # Mock test case generation (one call per endpoint, petstore has 3)
        mock_tc_client = MagicMock()
        mock_tc_client.call.side_effect = [
            MOCK_TC_GET_PETS,
            MOCK_TC_POST_PETS,
            MOCK_TC_GET_PET_BY_ID,
        ]
        MockTCLlm.return_value = mock_tc_client

        # Mock code generation: 3 test files; conftest.py is rendered locally.
        mock_code_client = MagicMock()
        mock_code_client.call.side_effect = [
            MOCK_TEST_CODE_1,
            MOCK_TEST_CODE_2,
            MOCK_TEST_CODE_3,
        ]
        MockCodeLlm.return_value = mock_code_client

        output_dir = tmp_path / "output"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "run",
                str(FIXTURES / "petstore.yaml"),
                "-o",
                str(output_dir),
            ],
        )

        assert result.exit_code == 0
        assert (output_dir / "testcases.md").exists()
        assert (output_dir / "conftest.py").exists()
        assert (output_dir / "test_get_pets.py").exists()
        assert (output_dir / "test_post_pets.py").exists()
        assert (output_dir / "test_get_pets_by_pet_id.py").exists()

        # Verify test cases file has content
        testcases_content = (output_dir / "testcases.md").read_text()
        assert "TC-001" in testcases_content
        assert "TC-006" in testcases_content

    @patch("api_test_gen.generator.layered.LlmClient")
    def test_layered_project_passes_real_collection(self, MockLlmClient):
        mock_client = MagicMock()
        mock_client.call.side_effect = [
            """```python
from base.client import HttpClient


class PetsApi:
    def __init__(self, client: HttpClient):
        self.client = client

    def list_pets(self):
        return self.client.get("/pets")
```""",
            """```yaml
list_pets:
  valid:
    expected_status: 200
```""",
            """```python
from api.pets_api import PetsApi


class PetsFlow:
    def __init__(self, api: PetsApi):
        self.api = api
```""",
            '''```python
class TestListPets:
    def test_success(self, pets_api):
        """TC-001: list pets"""
        resp = pets_api.list_pets()
        assert resp.status_code == 200
```''',
        ]
        MockLlmClient.return_value = mock_client
        endpoint = ApiEndpoint(
            method="GET", path="/pets", summary="List pets", tags=["pets"]
        )
        testcases = """## GET /pets

> List pets

| 编号 | 场景 | 输入 | 预期状态码 | 预期响应 | 优先级 |
|------|------|------|-----------|---------|--------|
| TC-001 | list pets | 无 | 200 | list returned | P0 |
"""

        files = LayeredCodeGenerator(model="test").generate(testcases, [endpoint])

        assert "api/pets_api.py" in files
        assert "services/pets_flow.py" in files
        assert "tests/test_pets.py" in files
