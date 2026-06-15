"""Layered code generator — produces 5-layer API automation project."""

from pathlib import Path

from api_test_agent.generator.common import (
    add_generated_file,
    extract_fenced_content,
    validate_and_repair,
)
from api_test_agent.generator.naming import group_endpoints_by_tag
from api_test_agent.generator.testcase_document import (
    TestCaseDocument,
    TestCaseDocumentError,
    parse_testcase_document,
)
from api_test_agent.llm import LlmClient
from api_test_agent.parser.base import ApiEndpoint

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class LayeredCodeGenerator:
    """Generates pytest code organized into a 5-layer architecture."""

    def __init__(self, model: str | None = None):
        self.client = LlmClient(model=model)

    def _group_by_tag(
        self, endpoints: list[ApiEndpoint]
    ) -> dict[str, list[ApiEndpoint]]:
        """Group endpoints by their first tag. Untagged endpoints go to 'default'."""
        return group_endpoints_by_tag(endpoints)

    def _render_config(self) -> str:
        return """import os

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8080")
API_TOKEN = os.getenv("API_TOKEN", "")
"""

    def _render_client(self) -> str:
        return """import requests
from .config import BASE_URL, API_TOKEN


class HttpClient:
    def __init__(self, base_url=BASE_URL, token=API_TOKEN):
        self.session = requests.Session()
        self.base_url = base_url
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def get(self, path, **kwargs):
        return self.session.get(f"{self.base_url}{path}", **kwargs)

    def post(self, path, **kwargs):
        return self.session.post(f"{self.base_url}{path}", **kwargs)

    def put(self, path, **kwargs):
        return self.session.put(f"{self.base_url}{path}", **kwargs)

    def delete(self, path, **kwargs):
        return self.session.delete(f"{self.base_url}{path}", **kwargs)

    def patch(self, path, **kwargs):
        return self.session.patch(f"{self.base_url}{path}", **kwargs)
"""

    def _render_requirements(self) -> str:
        return """requests>=2.28
pytest>=7.0
pyyaml>=6.0
"""

    def _render_jenkinsfile(self) -> str:
        return """pipeline {
    agent any

    parameters {
        choice(name: 'ENV', choices: ['dev', 'staging', 'prod'], description: '选择测试环境')
    }

    environment {
        API_BASE_URL = "${params.ENV == 'prod' ? 'https://api.example.com' : params.ENV == 'staging' ? 'https://staging-api.example.com' : 'http://dev-api.example.com'}"
        API_TOKEN = credentials('api-token')
    }

    stages {
        stage('Install') {
            steps {
                sh 'pip install -r requirements.txt'
            }
        }

        stage('Test') {
            steps {
                sh 'pytest tests/ -v --junitxml=reports/junit.xml'
            }
        }
    }

    post {
        always {
            junit 'reports/*.xml'
        }
    }
}
"""

    def _render_conftest(self, tag_names: list[str]) -> str:
        imports = ["import pytest", "from base.client import HttpClient"]
        fixtures = [
            "",
            "",
            "@pytest.fixture",
            "def client():",
            "    return HttpClient()",
        ]
        for tag in tag_names:
            class_name = tag.title().replace("_", "") + "Api"
            imports.append(f"from api.{tag}_api import {class_name}")
            fixtures.extend(
                [
                    "",
                    "",
                    "@pytest.fixture",
                    f"def {tag}_api(client):",
                    f"    return {class_name}(client)",
                ]
            )
        return "\n".join(imports + fixtures) + "\n"

    def _extract_sections_for_endpoints(
        self, testcases_md: str, endpoints: list[ApiEndpoint]
    ) -> str:
        """Extract testcase sections that match the given endpoints."""
        document = parse_testcase_document(testcases_md)
        return self._select_sections(document, endpoints)

    def _select_sections(
        self, document: TestCaseDocument, endpoints: list[ApiEndpoint]
    ) -> str:
        section_map = document.section_map()
        selected = []
        for endpoint in endpoints:
            key = (endpoint.method, endpoint.path)
            section = section_map.get(key)
            if section is None:
                raise TestCaseDocumentError(
                    f"Missing test-case section: {endpoint.method} {endpoint.path}"
                )
            selected.append(section.markdown)
        return "\n\n".join(selected)

    # -- orchestration --------------------------------------------------------

    def generate(
        self, testcases_md: str, endpoints: list[ApiEndpoint]
    ) -> dict[str, str]:
        """Generate all files for the layered architecture.

        Returns dict of {filepath: content} with paths like 'base/config.py'.
        """
        files: dict[str, str] = {}
        document = parse_testcase_document(testcases_md)
        groups = self._group_by_tag(endpoints)
        tag_names = sorted(groups.keys())

        # Static: base layer
        add_generated_file(files, "base/__init__.py", "")
        add_generated_file(files, "base/config.py", self._render_config())
        add_generated_file(files, "base/client.py", self._render_client())

        # Static: requirements + Jenkinsfile
        add_generated_file(files, "requirements.txt", self._render_requirements())
        add_generated_file(files, "Jenkinsfile", self._render_jenkinsfile())

        # Init files for other layers
        add_generated_file(files, "api/__init__.py", "")
        add_generated_file(files, "services/__init__.py", "")
        add_generated_file(files, "tests/__init__.py", "")

        # Dynamic: per-tag generation
        for tag in tag_names:
            tag_endpoints = groups[tag]
            testcases_section = self._select_sections(document, tag_endpoints)

            # API layer
            api_filename, api_code = self._generate_api_layer(tag, tag_endpoints)
            add_generated_file(files, f"api/{api_filename}", api_code)

            # Data layer
            data_filename, data_content = self._generate_data_layer(
                tag, testcases_section
            )
            add_generated_file(files, f"data/{data_filename}", data_content)

            # Services layer
            svc_filename, svc_code = self._generate_services_layer(
                tag, tag_endpoints, api_code
            )
            add_generated_file(files, f"services/{svc_filename}", svc_code)

            # Tests layer
            test_filename, test_code = self._generate_tests_layer(
                tag, testcases_section, api_code, data_content
            )
            add_generated_file(files, f"tests/{test_filename}", test_code)

        # Static: conftest (needs tag_names for fixtures)
        add_generated_file(files, "tests/conftest.py", self._render_conftest(tag_names))

        return validate_and_repair(files, self._retry_failed)

    # -- shared helpers -------------------------------------------------------

    def _extract_code(self, response: str, lang: str = "python") -> str:
        """Extract code from markdown code block."""
        return extract_fenced_content(response, lang)

    def _retry_failed(
        self, files: dict[str, str], errors: dict[str, str]
    ) -> dict[str, str]:
        """Re-generate files that failed validation."""
        for filepath, error_msg in errors.items():
            if filepath == "_collect" or filepath not in files:
                continue
            if filepath.endswith(".py"):
                response = self.client.call(
                    system="你是一个代码修复助手。只输出一个 ```python 代码块，不要任何解释。",
                    user=(
                        f"请修复以下 Python 代码的错误并重新生成。\n\n"
                        f"错误信息：{error_msg}\n\n"
                        f"原始代码：\n```python\n{files[filepath]}\n```"
                    ),
                )
                files[filepath] = self._extract_code(response, "python")
            elif filepath.endswith((".yaml", ".yml")):
                response = self.client.call(
                    system="你是一个代码修复助手。只输出一个 ```yaml 代码块，不要任何解释。",
                    user=(
                        f"请修复以下 YAML 文件的格式错误并重新生成。\n\n"
                        f"错误信息：{error_msg}\n\n"
                        f"原始内容：\n```yaml\n{files[filepath]}\n```"
                    ),
                )
                files[filepath] = self._extract_code(response, "yaml")
        return files

    # -- LLM-based layer generation -------------------------------------------

    def _generate_api_layer(
        self, tag: str, endpoints: list[ApiEndpoint]
    ) -> tuple[str, str]:
        """Generate API wrapper class for a tag group. Returns (filename, code)."""
        prompt = (PROMPTS_DIR / "layered_api.md").read_text(encoding="utf-8")
        endpoints_json = "\n".join(ep.model_dump_json(indent=2) for ep in endpoints)
        response = self.client.call(
            system=prompt,
            user=f"为 tag '{tag}' 下的以下接口生成封装类：\n\n{endpoints_json}",
        )
        code = self._extract_code(response, "python")
        return f"{tag}_api.py", code

    def _generate_data_layer(self, tag: str, testcases_section: str) -> tuple[str, str]:
        """Generate YAML test data file for a tag group. Returns (filename, content)."""
        prompt = (PROMPTS_DIR / "layered_data.md").read_text(encoding="utf-8")
        response = self.client.call(
            system=prompt,
            user=f"为 tag '{tag}' 从以下测试用例中提取测试数据：\n\n{testcases_section}",
        )
        content = self._extract_code(response, "yaml")
        return f"{tag}.yaml", content

    def _generate_services_layer(
        self, tag: str, endpoints: list[ApiEndpoint], api_code: str
    ) -> tuple[str, str]:
        """Generate business flow class for a tag group. Returns (filename, code)."""
        prompt = (PROMPTS_DIR / "layered_services.md").read_text(encoding="utf-8")
        endpoints_json = "\n".join(ep.model_dump_json(indent=2) for ep in endpoints)
        response = self.client.call(
            system=prompt,
            user=(
                f"为 tag '{tag}' 生成业务编排类。\n\n"
                f"已有的接口封装类：\n```python\n{api_code}\n```\n\n"
                f"接口定义：\n{endpoints_json}"
            ),
        )
        code = self._extract_code(response, "python")
        return f"{tag}_flow.py", code

    def _generate_tests_layer(
        self, tag: str, testcases_section: str, api_code: str, data_content: str
    ) -> tuple[str, str]:
        """Generate test file for a tag group. Returns (filename, code)."""
        prompt = (PROMPTS_DIR / "layered_tests.md").read_text(encoding="utf-8")
        response = self.client.call(
            system=prompt,
            user=(
                f"为 tag '{tag}' 生成测试代码。\n\n"
                f"测试用例：\n{testcases_section}\n\n"
                f"接口封装类：\n```python\n{api_code}\n```\n\n"
                f"测试数据文件 ({tag}.yaml)：\n```yaml\n{data_content}\n```"
            ),
        )
        code = self._extract_code(response, "python")
        return f"test_{tag}.py", code
