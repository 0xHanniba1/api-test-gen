"""Code generator — converts test case documents into pytest+requests code."""

from pathlib import Path

from api_test_agent.generator.common import (
    add_generated_file,
    extract_fenced_content,
    validate_and_repair,
)
from api_test_agent.generator.naming import assign_endpoint_filenames
from api_test_agent.generator.testcase_document import (
    EndpointSection,
    parse_testcase_document,
)
from api_test_agent.llm import LlmClient

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class CodeGenerator:
    """Generates pytest + requests code files from test case Markdown documents."""

    def __init__(self, model: str | None = None):
        self.client = LlmClient(model=model)
        self.prompt_template = (PROMPTS_DIR / "code.md").read_text(encoding="utf-8")

    def generate(self, testcases_markdown: str) -> dict[str, str]:
        """Generate code files from test case Markdown.

        Returns a dict of {filename: code_content}.
        """
        files: dict[str, str] = {}
        document = parse_testcase_document(testcases_markdown)
        filenames = assign_endpoint_filenames(document.sections)

        add_generated_file(files, "conftest.py", self._render_conftest())

        for section in document.sections:
            filename = filenames[section.key]
            code = self._generate_test_file(section, filename)
            add_generated_file(files, filename, code)

        return validate_and_repair(files, self._retry_failed)

    def _render_conftest(self) -> str:
        return """import os

import pytest


@pytest.fixture
def base_url():
    return os.getenv("API_BASE_URL", "http://localhost:8080")


@pytest.fixture
def auth_headers():
    token = os.getenv("API_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}
"""

    def _generate_test_file(self, section: EndpointSection, filename: str) -> str:
        response = self.client.call(
            system=self.prompt_template,
            user=(
                f"Generate the contents of {filename} for the following endpoint. "
                "Return Python code only; the output path is assigned by the caller.\n\n"
                f"{section.markdown}"
            ),
        )
        return self._extract_code(response)

    def _extract_code(self, response: str) -> str:
        """Extract Python code from Markdown code blocks."""
        return extract_fenced_content(response, "python")

    def _retry_failed(
        self, files: dict[str, str], errors: dict[str, str]
    ) -> dict[str, str]:
        """Re-generate files that failed validation."""
        for filename, error_msg in errors.items():
            if filename == "_collect":
                continue
            if filename.endswith(".py") and filename in files:
                response = self.client.call(
                    system=self.prompt_template,
                    user=(
                        f"上次生成的 {filename} 有错误：{error_msg}\n\n"
                        f"请修复并重新生成。原始代码：\n```python\n{files[filename]}\n```"
                    ),
                )
                files[filename] = self._extract_code(response)
        return files
