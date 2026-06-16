from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from api_test_gen.cli import main
from api_test_gen.generator.common import GenerationValidationError
from api_test_gen.generator.testcase_document import TestCaseDocumentError
from api_test_gen.parser.base import ApiEndpoint
from api_test_gen.pipeline import filter_endpoints

FIXTURES = Path(__file__).parent / "fixtures"


def _make_endpoint(method: str, path: str) -> ApiEndpoint:
    return ApiEndpoint(
        method=method,
        path=path,
        summary="",
        parameters=[],
        request_body=None,
        responses={},
        auth_required=False,
        tags=[],
    )


class TestCliGenCases:
    @patch("api_test_gen.cli.generate_testcases")
    def test_gen_cases_with_swagger(self, mock_generate, tmp_path):
        mock_generate.return_value = "## GET /pets\n| TC-001 | ... |"
        output_file = tmp_path / "cases.md"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "gen-cases",
                str(FIXTURES / "petstore.yaml"),
                "-o",
                str(output_file),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()
        mock_generate.assert_called_once()

    @patch("api_test_gen.cli.generate_testcases", return_value="## GET /pets")
    @patch("api_test_gen.cli.parse_document")
    def test_markdown_model_is_forwarded(self, mock_parse, _mock_generate, tmp_path):
        mock_parse.return_value = [_make_endpoint("GET", "/pets")]
        doc = tmp_path / "api.md"
        doc.write_text("# API", encoding="utf-8")

        result = CliRunner().invoke(
            main,
            [
                "gen-cases",
                str(doc),
                "-o",
                str(tmp_path / "cases.md"),
                "--format",
                "markdown",
                "--model",
                "custom-model",
            ],
        )

        assert result.exit_code == 0
        mock_parse.assert_called_once_with(doc, "markdown", model="custom-model")

    def test_parse_error_is_user_facing(self, tmp_path):
        doc = tmp_path / "broken.yaml"
        doc.write_text("openapi: 3.0.0\npaths: [invalid", encoding="utf-8")

        result = CliRunner().invoke(
            main,
            [
                "gen-cases",
                str(doc),
                "-o",
                str(tmp_path / "cases.md"),
                "--format",
                "swagger",
            ],
        )

        assert result.exit_code != 0
        assert "Failed to parse" in result.output
        assert "Traceback" not in result.output

    @patch("api_test_gen.cli.generate_testcases")
    def test_generation_error_is_user_facing(self, mock_generate, tmp_path):
        mock_generate.side_effect = TestCaseDocumentError(
            "Invalid test-case JSON: expected an array"
        )
        output = tmp_path / "cases.md"

        result = CliRunner().invoke(
            main,
            [
                "gen-cases",
                str(FIXTURES / "petstore.yaml"),
                "-o",
                str(output),
            ],
        )

        assert result.exit_code != 0
        assert "Invalid test-case JSON" in result.output
        assert "Traceback" not in result.output
        assert not output.exists()


class TestCliGenCode:
    @patch("api_test_gen.cli.generate_code")
    def test_gen_code_from_markdown(self, mock_generate, tmp_path):
        # Create input test cases file
        cases_file = tmp_path / "cases.md"
        cases_file.write_text("## POST /api/users\n| TC-001 | test | ... |")

        mock_generate.return_value = {
            "conftest.py": "# conftest",
            "test_users.py": "# test code",
        }

        output_dir = tmp_path / "output"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "gen-code",
                str(cases_file),
                "-o",
                str(output_dir),
            ],
        )

        assert result.exit_code == 0
        assert (output_dir / "conftest.py").exists()
        assert (output_dir / "test_users.py").exists()

    @patch("api_test_gen.cli.generate_code")
    def test_rejects_generated_path_outside_output(self, mock_generate, tmp_path):
        mock_generate.return_value = {"../escape.py": "# unsafe"}
        cases_file = tmp_path / "cases.md"
        cases_file.write_text("## GET /pets", encoding="utf-8")

        result = CliRunner().invoke(
            main, ["gen-code", str(cases_file), "-o", str(tmp_path / "output")]
        )

        assert result.exit_code != 0
        assert "Unsafe generated path" in result.output
        assert not (tmp_path / "escape.py").exists()

    @patch("api_test_gen.cli.generate_code")
    def test_reports_validation_failure(self, mock_generate, tmp_path):
        mock_generate.side_effect = GenerationValidationError(
            {"test_pets.py": "SyntaxError: invalid syntax"}
        )
        cases_file = tmp_path / "cases.md"
        cases_file.write_text("## GET /pets", encoding="utf-8")

        result = CliRunner().invoke(
            main, ["gen-code", str(cases_file), "-o", str(tmp_path / "output")]
        )

        assert result.exit_code != 0
        assert "Generated files failed validation" in result.output


class TestCliRun:
    @patch("api_test_gen.cli.generate_code")
    @patch("api_test_gen.cli.generate_testcases")
    def test_run_full_pipeline(self, mock_testcases, mock_code, tmp_path):
        mock_testcases.return_value = "## GET /pets\n| TC-001 | ... |"
        mock_code.return_value = {
            "conftest.py": "# conftest",
            "test_pets.py": "# tests",
        }

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
        mock_testcases.assert_called_once()
        mock_code.assert_called_once()


class TestFilterEndpoints:
    def test_filter_by_method_and_path(self):
        endpoints = [
            _make_endpoint("GET", "/pets"),
            _make_endpoint("POST", "/pets"),
            _make_endpoint("GET", "/users"),
        ]
        result = filter_endpoints(endpoints, ("POST /pets",))
        assert len(result) == 1
        assert result[0].method == "POST"
        assert result[0].path == "/pets"

    def test_filter_by_path_only(self):
        endpoints = [
            _make_endpoint("GET", "/pets"),
            _make_endpoint("POST", "/pets/123"),
            _make_endpoint("GET", "/users"),
        ]
        result = filter_endpoints(endpoints, ("/pets/*",))
        assert len(result) == 1
        assert result[0].path == "/pets/123"

    def test_filter_no_match(self):
        endpoints = [
            _make_endpoint("GET", "/pets"),
            _make_endpoint("POST", "/pets"),
        ]
        result = filter_endpoints(endpoints, ("DELETE /orders",))
        assert len(result) == 0


class TestAppendMode:
    @patch(
        "api_test_gen.cli.generate_testcases",
        return_value="""## POST /new

| 编号 | 场景 | 输入 | 预期状态码 | 预期响应 | 优先级 |
|------|------|------|-----------|---------|--------|
| TC-008 | new | 无 | 201 | ok | P0 |""",
    )
    def test_gen_cases_append(self, mock_generate, tmp_path):
        output_file = tmp_path / "cases.md"
        output_file.write_text(
            """## GET /existing

| 编号 | 场景 | 输入 | 预期状态码 | 预期响应 | 优先级 |
|------|------|------|-----------|---------|--------|
| TC-007 | existing | 无 | 200 | ok | P0 |
""",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "gen-cases",
                str(FIXTURES / "petstore.yaml"),
                "-o",
                str(output_file),
                "--append",
            ],
        )

        assert result.exit_code == 0
        content = output_file.read_text(encoding="utf-8")
        assert "## GET /existing" in content
        assert "## POST /new" in content
        assert "TC-008" in content
        assert mock_generate.call_args.kwargs["start_index"] == 8

    @patch("api_test_gen.cli.generate_testcases")
    def test_gen_cases_append_rejects_duplicate_endpoint(self, mock_generate, tmp_path):
        output_file = tmp_path / "cases.md"
        output_file.write_text(
            """## GET /pets

| 编号 | 场景 | 输入 | 预期状态码 | 预期响应 | 优先级 |
|------|------|------|-----------|---------|--------|
| TC-001 | existing | 无 | 200 | ok | P0 |
""",
            encoding="utf-8",
        )

        result = CliRunner().invoke(
            main,
            [
                "gen-cases",
                str(FIXTURES / "petstore.yaml"),
                "-o",
                str(output_file),
                "--append",
            ],
        )

        assert result.exit_code != 0
        assert "duplicate endpoint sections: GET /pets" in result.output
        mock_generate.assert_not_called()

    @patch("api_test_gen.cli.generate_code")
    def test_gen_code_append_skips_existing(self, mock_generate, tmp_path):
        mock_generate.return_value = {
            "conftest.py": "# new conftest",
            "test_pets.py": "# new test",
        }

        cases_file = tmp_path / "cases.md"
        cases_file.write_text("## POST /pets\n| TC-001 | test |")

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        existing = output_dir / "conftest.py"
        existing.write_text("# original conftest", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "gen-code",
                str(cases_file),
                "-o",
                str(output_dir),
                "--append",
            ],
        )

        assert result.exit_code == 0
        assert existing.read_text(encoding="utf-8") == "# original conftest"
        assert (output_dir / "test_pets.py").read_text(encoding="utf-8") == "# new test"


class TestCliGenCodeLayered:
    @patch("api_test_gen.cli.generate_code")
    def test_gen_code_layered_requires_doc(self, mock_generate, tmp_path):
        """--arch layered requires --doc for endpoint info."""
        cases_file = tmp_path / "cases.md"
        cases_file.write_text("## POST /api/users\n| TC-001 | test | ... |")

        mock_generate.return_value = {
            "base/config.py": "# config",
            "tests/test_users.py": "# test",
        }

        output_dir = tmp_path / "output"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "gen-code",
                str(cases_file),
                "-o",
                str(output_dir),
                "--arch",
                "layered",
                "--doc",
                str(FIXTURES / "petstore.yaml"),
            ],
        )

        assert result.exit_code == 0
        mock_generate.assert_called_once()

    @patch("api_test_gen.cli.generate_code")
    def test_gen_code_layered_without_doc_fails(self, mock_generate, tmp_path):
        """--arch layered without --doc should error."""
        cases_file = tmp_path / "cases.md"
        cases_file.write_text("## POST /api/users\n| TC-001 | test | ... |")

        output_dir = tmp_path / "output"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "gen-code",
                str(cases_file),
                "-o",
                str(output_dir),
                "--arch",
                "layered",
            ],
        )

        assert result.exit_code != 0
        assert "--doc" in result.output
        mock_generate.assert_not_called()


class TestCliRunLayered:
    @patch("api_test_gen.cli.generate_code")
    @patch("api_test_gen.cli.generate_testcases")
    def test_run_layered(self, mock_testcases, mock_code, tmp_path):
        mock_testcases.return_value = "## GET /pets\n| TC-001 | ... |"
        mock_code.return_value = {
            "base/config.py": "# config",
            "tests/test_pets.py": "# tests",
        }

        output_dir = tmp_path / "output"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "run",
                str(FIXTURES / "petstore.yaml"),
                "-o",
                str(output_dir),
                "--arch",
                "layered",
            ],
        )

        assert result.exit_code == 0
        mock_testcases.assert_called_once()
        mock_code.assert_called_once()
