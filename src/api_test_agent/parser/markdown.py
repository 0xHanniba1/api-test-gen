"""Markdown/text API documentation parser.

Uses LLM to extract structured API endpoint definitions
from unstructured text documents.
"""

import json
import re
from pathlib import Path

from api_test_agent.llm import LlmClient
from api_test_agent.parser.base import ApiEndpoint

SYSTEM_PROMPT = """You are an API documentation parser. Extract all API endpoints from the given document.

Output a JSON array of endpoint objects. Each object must have these fields:
- method: HTTP method (GET/POST/PUT/DELETE/PATCH)
- path: URL path (e.g., /api/users/{id})
- summary: Brief description
- description: Detailed description (empty string if missing)
- operation_id: Stable operation identifier (empty string if missing)
- parameters: Array of {name, location (query/path/header/cookie), required (bool), param_type (string/integer/boolean/array/object), description, constraints, example}
- request_body: JSON Schema object or null
- request_body_required: boolean
- responses: Object of {status_code: {description}}
- auth_required: boolean
- tags: Array of strings
- content_type: string (default "application/json")
- content_types: Array of supported request content types

Output ONLY the JSON array, no other text."""


def parse_markdown(file_path: Path, model: str | None = None) -> list[ApiEndpoint]:
    """Parse a Markdown/text API document using LLM extraction."""
    text = file_path.read_text(encoding="utf-8")

    client = LlmClient(model=model)
    response = client.call(system=SYSTEM_PROMPT, user=text)

    # Extract JSON from response (might be wrapped in code blocks)
    json_str = _extract_json(response)
    data = json.loads(json_str)

    return [ApiEndpoint(**item) for item in data]


def _extract_json(text: str) -> str:
    """Extract JSON from a response that might contain Markdown code blocks."""
    match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()
