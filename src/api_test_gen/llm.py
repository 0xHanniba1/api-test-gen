"""LLM client wrapper around litellm.

Provides a unified interface for calling any LLM model supported by litellm.
"""

from litellm import completion

DEFAULT_MODEL = "claude-sonnet-4-20250514"


class LlmClient:
    """Wrapper for LLM API calls via litellm."""

    def __init__(self, model: str | None = None):
        self.model = model or DEFAULT_MODEL

    def call(self, system: str, user: str) -> str:
        """Send a system+user message to the LLM and return the response text."""
        response = completion(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content
