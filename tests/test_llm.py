from unittest.mock import patch, MagicMock
from api_test_gen.llm import LlmClient


class TestLlmClient:
    def test_default_model(self):
        client = LlmClient()
        assert client.model is not None

    def test_custom_model(self):
        client = LlmClient(model="gpt-4o")
        assert client.model == "gpt-4o"

    @patch("api_test_gen.llm.completion")
    def test_call_returns_content(self, mock_completion):
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "test response"
        mock_completion.return_value = mock_resp

        client = LlmClient(model="gpt-4o")
        result = client.call(system="You are helpful.", user="Hello")
        assert result == "test response"
        mock_completion.assert_called_once()

    @patch("api_test_gen.llm.completion")
    def test_call_passes_model_and_messages(self, mock_completion):
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "ok"
        mock_completion.return_value = mock_resp

        client = LlmClient(model="claude-sonnet-4-20250514")
        client.call(system="sys", user="usr")

        call_kwargs = mock_completion.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
