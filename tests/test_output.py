import pytest

from api_test_agent.output import (
    OutputPathConflictError,
    UnsafeOutputPathError,
    write_generated_files,
    write_text,
)


class TestWriteText:
    def test_appends_to_existing_content(self, tmp_path):
        output = tmp_path / "cases.md"
        output.write_text("existing", encoding="utf-8")

        write_text(output, "new", append=True)

        assert output.read_text(encoding="utf-8") == "existing\nnew"


class TestWriteGeneratedFiles:
    def test_writes_nested_files(self, tmp_path):
        result = write_generated_files(
            tmp_path / "output", {"tests/test_users.py": "# test"}
        )

        assert len(result.created) == 1
        assert (tmp_path / "output/tests/test_users.py").read_text() == "# test"

    def test_append_skips_existing_files(self, tmp_path):
        output = tmp_path / "output"
        output.mkdir()
        existing = output / "test_users.py"
        existing.write_text("old", encoding="utf-8")

        result = write_generated_files(
            output,
            {"test_users.py": "new", "test_pets.py": "pets"},
            append=True,
        )

        assert existing.read_text(encoding="utf-8") == "old"
        assert len(result.skipped) == 1
        assert len(result.created) == 1

    @pytest.mark.parametrize("path", ["../escape.py", "/tmp/escape.py", ""])
    def test_rejects_unsafe_paths_before_writing(self, tmp_path, path):
        output = tmp_path / "output"

        with pytest.raises(UnsafeOutputPathError):
            write_generated_files(output, {path: "unsafe", "safe.py": "safe"})

        assert not output.exists()

    def test_rejects_paths_that_resolve_to_same_file(self, tmp_path):
        output = tmp_path / "output"

        with pytest.raises(OutputPathConflictError):
            write_generated_files(
                output, {"tests/test.py": "first", "tests/./test.py": "second"}
            )

        assert not output.exists()

    def test_rejects_symlink_escape(self, tmp_path):
        output = tmp_path / "output"
        outside = tmp_path / "outside"
        output.mkdir()
        outside.mkdir()
        (output / "linked").symlink_to(outside, target_is_directory=True)

        with pytest.raises(UnsafeOutputPathError):
            write_generated_files(output, {"linked/escape.py": "unsafe"})

        assert not (outside / "escape.py").exists()
