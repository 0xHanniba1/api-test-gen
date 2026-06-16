"""Auto-detect API documentation format."""

from pathlib import Path

import yaml


def detect_format(file_path: Path) -> str:
    """Detect the format of an API documentation file.

    Returns: 'swagger', 'postman', or 'markdown'.
    """
    text = file_path.read_text(encoding="utf-8")

    # Try YAML/JSON parsing
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict):
            if "openapi" in data or "swagger" in data:
                return "swagger"
            if _is_postman_collection(data):
                return "postman"
    except yaml.YAMLError:
        pass

    return "markdown"


def _is_postman_collection(data: dict) -> bool:
    info = data.get("info", {})
    schema = info.get("schema", "") if isinstance(info, dict) else ""
    return bool(
        isinstance(info, dict)
        and ("_postman_id" in info or "schema.getpostman.com" in str(schema))
        and isinstance(data.get("item"), list)
    )
