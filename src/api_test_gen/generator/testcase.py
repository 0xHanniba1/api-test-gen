"""Test case generator — uses LLM + skills to produce test case documents."""

from pathlib import Path

from api_test_gen.llm import LlmClient
from api_test_gen.parser.base import ApiEndpoint
from api_test_gen.skills.loader import select_skills, load_skill_content
from api_test_gen.generator.testcase_document import (
    TestCaseDocumentError,
    TestCaseDraft,
    parse_drafts,
    render_endpoint_section,
)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class TestCaseGenerator:
    """Generates test case Markdown documents from API endpoint definitions."""

    def __init__(self, model: str | None = None):
        self.client = LlmClient(model=model)
        self.prompt_template = (PROMPTS_DIR / "testcase.md").read_text(encoding="utf-8")

    def generate(
        self,
        endpoints: list[ApiEndpoint],
        depth: str = "quick",
        start_index: int = 1,
    ) -> str:
        """Generate test cases for all endpoints, returns Markdown string."""
        results = []
        next_index = start_index
        seen_endpoints: set[tuple[str, str]] = set()
        for endpoint in endpoints:
            key = (endpoint.method, endpoint.path)
            if key in seen_endpoints:
                raise TestCaseDocumentError(
                    f"Duplicate endpoint definition: {endpoint.method} {endpoint.path}"
                )
            seen_endpoints.add(key)

            drafts = self._generate_for_endpoint(endpoint, depth)
            section, next_index = render_endpoint_section(endpoint, drafts, next_index)
            results.append(section)
        return "\n\n".join(results)

    def _generate_for_endpoint(
        self, endpoint: ApiEndpoint, depth: str
    ) -> list[TestCaseDraft]:
        skill_names = select_skills(endpoint, depth)
        skill_content = load_skill_content(skill_names)

        system_prompt = f"{skill_content}\n\n---\n\n{self.prompt_template}"

        user_prompt = (
            f"请为以下接口生成测试用例，深度级别：{depth}\n\n"
            f"```json\n{endpoint.model_dump_json(indent=2)}\n```"
        )

        response = self.client.call(system=system_prompt, user=user_prompt)
        return parse_drafts(response)
