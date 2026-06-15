"""Postman Collection v2.1 parser."""

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .base import ApiEndpoint, Param


def parse_postman(file_path: Path) -> list[ApiEndpoint]:
    """Parse a Postman Collection v2.1 file into normalized endpoints."""
    collection = json.loads(file_path.read_text(encoding="utf-8"))
    endpoints: list[ApiEndpoint] = []
    _parse_items(
        collection.get("item", []),
        endpoints,
        inherited_auth=collection.get("auth"),
        folder_tags=(),
    )
    return endpoints


def _parse_items(
    items: list[dict[str, Any]],
    endpoints: list[ApiEndpoint],
    inherited_auth: dict[str, Any] | None,
    folder_tags: tuple[str, ...],
) -> None:
    for item in items:
        if "item" in item:
            folder_auth = item.get("auth", inherited_auth)
            folder_name = item.get("name")
            nested_tags = (*folder_tags, folder_name) if folder_name else folder_tags
            _parse_items(item["item"], endpoints, folder_auth, nested_tags)
        elif "request" in item:
            endpoints.append(_parse_request(item, inherited_auth, folder_tags))


def _parse_request(
    item: dict[str, Any],
    inherited_auth: dict[str, Any] | None,
    folder_tags: tuple[str, ...],
) -> ApiEndpoint:
    request = item["request"]
    url = request.get("url", {})
    headers = [
        header for header in request.get("header", []) if not header.get("disabled")
    ]
    path = _parse_path(url)
    parameters = _parse_query_params(url)
    parameters.extend(_parse_path_params(url, path))
    parameters.extend(_parse_header_params(headers))
    body, body_required, content_types = _parse_body(request.get("body"), headers)

    return ApiEndpoint(
        method=request.get("method", "GET"),
        path=path,
        summary=item.get("name", ""),
        description=_description_text(
            request.get("description", item.get("description", ""))
        ),
        parameters=_deduplicate_params(parameters),
        request_body=body,
        request_body_required=body_required,
        responses=_parse_saved_responses(item.get("response", [])),
        auth_required=_requires_auth(request, inherited_auth, headers),
        tags=list(folder_tags),
        content_types=content_types or ["application/json"],
    )


def _parse_path(url: Any) -> str:
    if isinstance(url, str):
        return _path_from_raw(url)
    if not isinstance(url, dict):
        return "/"

    path_parts = url.get("path")
    if isinstance(path_parts, list):
        parts = [_path_part_value(part) for part in path_parts]
        path = "/" + "/".join(part for part in parts if part)
    elif isinstance(path_parts, str):
        path = path_parts
    else:
        path = _path_from_raw(url.get("raw", ""))
    return _normalize_path_variables(path)


def _path_from_raw(raw: str) -> str:
    raw = raw.split("?", 1)[0].split("#", 1)[0]
    if not raw:
        return "/"
    if "://" in raw:
        path = urlsplit(raw).path
    else:
        path = re.sub(r"^\{\{[^}]+\}\}", "", raw)
        if not path.startswith("/"):
            path = "/" + path.split("/", 1)[-1] if "/" in path else "/"
    return _normalize_path_variables(path or "/")


def _normalize_path_variables(path: str) -> str:
    normalized = re.sub(r"(?<=/):([A-Za-z_]\w*)", r"{\1}", path)
    normalized = re.sub(r"\{\{([^{}]+)\}\}", r"{\1}", normalized)
    return normalized if normalized.startswith("/") else f"/{normalized}"


def _parse_query_params(url: Any) -> list[Param]:
    if not isinstance(url, dict):
        return []
    result = []
    for query in url.get("query", []) or []:
        if query.get("disabled") or not query.get("key"):
            continue
        value = query.get("value")
        result.append(
            Param(
                name=str(query["key"]),
                location="query",
                param_type=_infer_primitive_type(value),
                description=_description_text(query.get("description", "")),
                example=value,
            )
        )
    return result


def _parse_path_params(url: Any, path: str) -> list[Param]:
    variables = {}
    if isinstance(url, dict):
        variables = {
            str(variable.get("key")): variable
            for variable in url.get("variable", []) or []
            if variable.get("key") and not variable.get("disabled")
        }

    result = []
    for name in re.findall(r"\{([^{}]+)\}", path):
        variable = variables.get(name, {})
        value = variable.get("value")
        result.append(
            Param(
                name=name,
                location="path",
                required=True,
                param_type=_infer_primitive_type(value),
                description=_description_text(variable.get("description", "")),
                example=value,
            )
        )
    return result


def _parse_header_params(headers: list[dict[str, Any]]) -> list[Param]:
    ignored = {"authorization", "content-type", "accept"}
    return [
        Param(
            name=str(header["key"]),
            location="header",
            param_type="string",
            description=_description_text(header.get("description", "")),
            example=header.get("value"),
        )
        for header in headers
        if header.get("key") and str(header["key"]).lower() not in ignored
    ]


def _parse_body(
    body: dict[str, Any] | None, headers: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, bool, list[str]]:
    if not body or body.get("disabled"):
        return None, False, []

    mode = body.get("mode")
    if mode == "raw":
        raw = body.get("raw", "")
        content_type = _content_type(headers) or _raw_content_type(body)
        if _is_json_content_type(content_type):
            try:
                return _schema_from_value(json.loads(raw)), True, [content_type]
            except (json.JSONDecodeError, TypeError):
                pass
        return {"type": "string", "example": raw}, True, [content_type or "text/plain"]

    if mode in {"urlencoded", "formdata"}:
        properties = {}
        for field in body.get(mode, []) or []:
            if field.get("disabled") or not field.get("key"):
                continue
            if mode == "formdata" and field.get("type") == "file":
                schema = {"type": "string", "format": "binary"}
            else:
                schema = _schema_from_value(field.get("value"))
            description = _description_text(field.get("description", ""))
            if description:
                schema["description"] = description
            properties[str(field["key"])] = schema
        content_type = (
            "multipart/form-data"
            if mode == "formdata"
            else "application/x-www-form-urlencoded"
        )
        return {"type": "object", "properties": properties}, True, [content_type]

    if mode == "graphql":
        graphql = body.get("graphql", {})
        value = {
            "query": graphql.get("query", ""),
            "variables": _parse_json_if_possible(graphql.get("variables", {})),
        }
        return _schema_from_value(value), True, ["application/json"]

    return None, False, []


def _parse_saved_responses(
    responses: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    parsed = {}
    for response in responses:
        status = str(response.get("code", "default"))
        result: dict[str, Any] = {
            "description": response.get("name", response.get("status", ""))
        }
        headers = response.get("header", []) or []
        content_type = _content_type(headers)
        body = response.get("body")
        if body not in (None, ""):
            if _is_json_content_type(content_type):
                try:
                    result["schema"] = _schema_from_value(json.loads(body))
                except (json.JSONDecodeError, TypeError):
                    result["schema"] = {"type": "string", "example": body}
            else:
                result["schema"] = {"type": "string", "example": body}
        if content_type:
            result["content_types"] = [content_type]
        parsed[status] = result
    return parsed


def _requires_auth(
    request: dict[str, Any],
    inherited_auth: dict[str, Any] | None,
    headers: list[dict[str, Any]],
) -> bool:
    auth = request["auth"] if "auth" in request else inherited_auth
    if isinstance(auth, dict) and auth.get("type"):
        return auth.get("type") != "noauth"
    return any(
        str(header.get("key", "")).lower() == "authorization" for header in headers
    )


def _content_type(headers: list[dict[str, Any]]) -> str | None:
    for header in headers:
        if str(header.get("key", "")).lower() == "content-type":
            return str(header.get("value", "")).split(";", 1)[0].strip() or None
    return None


def _raw_content_type(body: dict[str, Any]) -> str | None:
    language = body.get("options", {}).get("raw", {}).get("language")
    return {
        "json": "application/json",
        "xml": "application/xml",
        "html": "text/html",
        "javascript": "application/javascript",
        "text": "text/plain",
    }.get(language)


def _schema_from_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null", "example": None}
    if isinstance(value, bool):
        return {"type": "boolean", "example": value}
    if isinstance(value, int):
        return {"type": "integer", "example": value}
    if isinstance(value, float):
        return {"type": "number", "example": value}
    if isinstance(value, list):
        schema: dict[str, Any] = {"type": "array", "example": value}
        if value:
            schema["items"] = _schema_from_value(value[0])
        return schema
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {
                str(key): _schema_from_value(item) for key, item in value.items()
            },
            "example": value,
        }
    return {"type": "string", "example": value}


def _infer_primitive_type(value: Any) -> str:
    if isinstance(value, bool) or str(value).lower() in {"true", "false"}:
        return "boolean"
    try:
        int(str(value))
        return "integer"
    except (TypeError, ValueError):
        pass
    try:
        float(str(value))
        return "number"
    except (TypeError, ValueError):
        return "string"


def _deduplicate_params(parameters: list[Param]) -> list[Param]:
    result: dict[tuple[str, str], Param] = {}
    for parameter in parameters:
        result[(parameter.name, parameter.location)] = parameter
    return list(result.values())


def _description_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("content", ""))
    return ""


def _path_part_value(part: Any) -> str:
    if isinstance(part, str):
        return part
    if isinstance(part, dict):
        return str(part.get("value", part.get("key", "")))
    return str(part)


def _parse_json_if_possible(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _is_json_content_type(content_type: str | None) -> bool:
    return bool(
        content_type
        and (content_type == "application/json" or content_type.endswith("+json"))
    )
