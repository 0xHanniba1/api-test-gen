"""OpenAPI 3.x and Swagger 2.0 document parser."""

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .base import ApiEndpoint, Param

HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE"}
PREFERRED_CONTENT_TYPES = (
    "application/json",
    "multipart/form-data",
    "application/x-www-form-urlencoded",
)
CONSTRAINT_KEYS = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "multipleOf",
    "pattern",
    "enum",
    "format",
    "default",
    "collectionFormat",
)
RESERVED_HEADER_PARAMETERS = {"accept", "content-type", "authorization"}


def parse_openapi(file_path: Path) -> list[ApiEndpoint]:
    """Parse an OpenAPI or Swagger file into normalized endpoints."""
    document = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("OpenAPI document must be a mapping")

    endpoints = []
    paths = document.get("paths", {})
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI paths must be a mapping")

    for path, raw_path_item in paths.items():
        path_item = _resolve_local_refs(raw_path_item, document)
        if not isinstance(path_item, dict):
            continue
        path_parameters = path_item.get("parameters", [])

        for method, raw_operation in path_item.items():
            if method.upper() not in HTTP_METHODS or not isinstance(
                raw_operation, dict
            ):
                continue

            operation = _resolve_local_refs(raw_operation, document)
            raw_parameters = _merge_parameters(
                path_parameters, operation.get("parameters", []), document
            )
            parameters = _parse_parameters(raw_parameters)
            request_body, body_required, content_types = _parse_request_body(
                operation, raw_parameters, document
            )

            endpoints.append(
                ApiEndpoint(
                    method=method,
                    path=str(path),
                    summary=operation.get("summary", ""),
                    description=operation.get("description", ""),
                    operation_id=operation.get("operationId", ""),
                    parameters=parameters,
                    request_body=request_body,
                    request_body_required=body_required,
                    responses=_parse_responses(
                        operation.get("responses", {}), document
                    ),
                    auth_required=_requires_auth(operation, document),
                    tags=operation.get("tags", []),
                    content_types=content_types or ["application/json"],
                )
            )

    return endpoints


def _merge_parameters(
    path_parameters: Any, operation_parameters: Any, document: dict[str, Any]
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_parameter in [*(path_parameters or []), *(operation_parameters or [])]:
        parameter = _resolve_local_refs(raw_parameter, document)
        if not isinstance(parameter, dict):
            continue
        key = (str(parameter.get("name", "")), str(parameter.get("in", "query")))
        merged[key] = parameter
    return list(merged.values())


def _parse_parameters(parameters: list[dict[str, Any]]) -> list[Param]:
    result = []
    for parameter in parameters:
        location = parameter.get("in", "query")
        if location in {"body", "formData"} or "name" not in parameter:
            continue
        if (
            location == "header"
            and str(parameter["name"]).lower() in RESERVED_HEADER_PARAMETERS
        ):
            continue

        media = _select_media(parameter.get("content", {}))
        schema = (
            parameter.get("schema")
            or (media.get("schema") if media else None)
            or _swagger_parameter_schema(parameter)
        )
        result.append(
            Param(
                name=str(parameter["name"]),
                location=location,
                required=True
                if location == "path"
                else bool(parameter.get("required")),
                param_type=_schema_type(schema),
                description=parameter.get("description", ""),
                constraints={
                    key: schema[key] for key in CONSTRAINT_KEYS if key in schema
                },
                example=parameter.get(
                    "example",
                    media.get("example") if media else schema.get("example"),
                ),
            )
        )
    return result


def _parse_request_body(
    operation: dict[str, Any],
    parameters: list[dict[str, Any]],
    document: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool, list[str]]:
    if "requestBody" in operation:
        body = _resolve_local_refs(operation["requestBody"], document)
        if not isinstance(body, dict):
            return None, False, []
        if isinstance(body.get("$ref"), str):
            return body, bool(body.get("required")), ["application/json"]
        content = body.get("content", {})
        content_types = _ordered_content_types(content)
        media = _select_media(content)
        schema = media.get("schema") if media else None
        return schema, bool(body.get("required")), content_types

    body_parameter = next((p for p in parameters if p.get("in") == "body"), None)
    form_parameters = [p for p in parameters if p.get("in") == "formData"]
    content_types = list(operation.get("consumes", document.get("consumes", [])) or [])

    if body_parameter:
        return (
            body_parameter.get("schema"),
            bool(body_parameter.get("required")),
            content_types,
        )
    if form_parameters:
        properties = {}
        required = []
        for parameter in form_parameters:
            name = str(parameter.get("name", ""))
            if not name:
                continue
            properties[name] = _swagger_parameter_schema(parameter)
            if parameter.get("description"):
                properties[name]["description"] = parameter["description"]
            if parameter.get("required"):
                required.append(name)
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema, bool(required), content_types or ["multipart/form-data"]

    return None, False, content_types


def _parse_responses(
    responses: Any, document: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    result = {}
    if not isinstance(responses, dict):
        return result

    for status_code, raw_response in responses.items():
        response = _resolve_local_refs(raw_response, document)
        if not isinstance(response, dict):
            continue
        parsed: dict[str, Any] = {"description": response.get("description", "")}
        content = response.get("content", {})
        if isinstance(content, dict) and content:
            parsed["content_types"] = _ordered_content_types(content)
            media = _select_media(content)
            if media and media.get("schema") is not None:
                parsed["schema"] = media["schema"]
        elif response.get("schema") is not None:
            parsed["schema"] = response["schema"]
        result[str(status_code)] = parsed
    return result


def _requires_auth(operation: dict[str, Any], document: dict[str, Any]) -> bool:
    security = (
        operation["security"]
        if "security" in operation
        else document.get("security", [])
    )
    if not isinstance(security, list) or not security:
        return False
    if any(requirement == {} for requirement in security):
        return False
    return any(bool(requirement) for requirement in security)


def _select_media(content: Any) -> dict[str, Any] | None:
    content_types = _ordered_content_types(content)
    if not content_types:
        return None
    return content[content_types[0]]


def _ordered_content_types(content: Any) -> list[str]:
    if not isinstance(content, dict) or not content:
        return []
    content_types = list(content)
    for content_type in PREFERRED_CONTENT_TYPES:
        if content_type in content:
            return [
                content_type,
                *(item for item in content_types if item != content_type),
            ]
    for content_type in content_types:
        if content_type.endswith("+json"):
            return [
                content_type,
                *(item for item in content_types if item != content_type),
            ]
    return content_types


def _swagger_parameter_schema(parameter: dict[str, Any]) -> dict[str, Any]:
    schema = {
        key: deepcopy(parameter[key])
        for key in ("type", "format", "items", *CONSTRAINT_KEYS, "example")
        if key in parameter
    }
    if schema.get("type") == "file":
        schema = {"type": "string", "format": "binary"}
    return schema or {"type": "string"}


def _schema_type(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "string"
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return next((value for value in schema_type if value != "null"), "string")
    return schema_type or ("object" if "properties" in schema else "string")


def _resolve_local_refs(
    value: Any, document: dict[str, Any], stack: tuple[str, ...] = ()
) -> Any:
    if isinstance(value, list):
        return [_resolve_local_refs(item, document, stack) for item in value]
    if not isinstance(value, dict):
        return value

    reference = value.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/"):
        if reference in stack:
            return deepcopy(value)
        resolved = _resolve_json_pointer(document, reference)
        siblings = {key: item for key, item in value.items() if key != "$ref"}
        merged = deepcopy(resolved)
        if isinstance(merged, dict):
            merged.update(siblings)
        return _resolve_local_refs(merged, document, (*stack, reference))

    return {
        key: _resolve_local_refs(item, document, stack) for key, item in value.items()
    }


def _resolve_json_pointer(document: dict[str, Any], reference: str) -> Any:
    current: Any = document
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"Unresolvable local reference: {reference}")
        current = current[part]
    return current
