from pathlib import Path

import pytest

from api_test_agent.parser.detect import detect_format
from api_test_agent.parser.swagger import parse_openapi

FIXTURES = Path(__file__).parent / "fixtures"


class TestDetectFormat:
    def test_detect_openapi_yaml(self):
        assert detect_format(FIXTURES / "petstore.yaml") == "swagger"

    def test_detect_unknown_format(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# API Docs\nSome text")
        assert detect_format(f) == "markdown"

    def test_detect_swagger_2(self):
        assert detect_format(FIXTURES / "swagger2.yaml") == "swagger"


class TestOpenApiParser:
    def test_parse_petstore_endpoints_count(self):
        endpoints = parse_openapi(FIXTURES / "petstore.yaml")
        assert len(endpoints) == 3

    def test_parse_get_pets(self):
        endpoints = parse_openapi(FIXTURES / "petstore.yaml")
        get_pets = [e for e in endpoints if e.method == "GET" and e.path == "/pets"][0]
        assert get_pets.summary == "List all pets"
        assert len(get_pets.parameters) == 1
        assert get_pets.parameters[0].name == "limit"
        assert get_pets.parameters[0].required is False
        assert get_pets.auth_required is False

    def test_parse_post_pets_has_body(self):
        endpoints = parse_openapi(FIXTURES / "petstore.yaml")
        post_pets = [e for e in endpoints if e.method == "POST"][0]
        assert post_pets.request_body is not None
        assert "name" in post_pets.request_body["properties"]
        assert post_pets.auth_required is True

    def test_parse_path_param(self):
        endpoints = parse_openapi(FIXTURES / "petstore.yaml")
        get_pet = [e for e in endpoints if "{petId}" in e.path][0]
        assert get_pet.parameters[0].location == "path"
        assert get_pet.parameters[0].required is True


class TestOpenApiComplexParser:
    def test_resolves_path_parameters_request_body_and_response_schema(self):
        endpoints = parse_openapi(FIXTURES / "openapi-complex.yaml")
        create = next(
            endpoint
            for endpoint in endpoints
            if endpoint.operation_id == "createTenantUser"
        )

        assert create.description == "Creates a user inside a tenant."
        assert [(p.name, p.location) for p in create.parameters] == [
            ("tenantId", "path"),
            ("X-Trace-ID", "header"),
        ]
        assert create.parameters[0].constraints["minLength"] == 3
        assert create.parameters[1].example == "trace-123"
        assert create.request_body_required is True
        assert (
            create.request_body["properties"]["manager"]["properties"]["id"]["type"]
            == "integer"
        )
        assert (
            create.responses["201"]["schema"]["properties"]["name"]["type"] == "string"
        )
        assert create.auth_required is True

    def test_operation_parameter_overrides_path_parameter_and_security(self):
        endpoints = parse_openapi(FIXTURES / "openapi-complex.yaml")
        public = next(
            endpoint
            for endpoint in endpoints
            if endpoint.operation_id == "getPublicUser"
        )

        assert len(public.parameters) == 1
        assert public.parameters[0].param_type == "string"
        assert public.parameters[0].constraints["pattern"] == "^[a-z0-9-]+$"
        assert public.auth_required is False
        assert public.responses["200"]["content_types"] == [
            "application/vnd.example+json"
        ]

    def test_detects_multipart_request_body(self):
        endpoints = parse_openapi(FIXTURES / "openapi-complex.yaml")
        upload = next(
            endpoint
            for endpoint in endpoints
            if endpoint.operation_id == "uploadAvatar"
        )

        assert upload.content_type == "multipart/form-data"
        assert upload.request_body_required is True
        assert upload.request_body["properties"]["file"]["format"] == "binary"

    def test_empty_security_requirement_makes_auth_optional(self):
        endpoints = parse_openapi(FIXTURES / "openapi-complex.yaml")
        optional = next(
            endpoint
            for endpoint in endpoints
            if endpoint.operation_id == "optionalAuth"
        )

        assert optional.auth_required is False

    def test_unresolvable_local_reference_fails_explicitly(self, tmp_path):
        document = tmp_path / "broken.yaml"
        document.write_text(
            """openapi: 3.0.0
info: {title: Broken, version: 1.0.0}
paths:
  /broken:
    get:
      parameters:
        - $ref: '#/components/parameters/Missing'
      responses: {'200': {description: OK}}
""",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Unresolvable local reference"):
            parse_openapi(document)

    def test_remote_reference_is_preserved_without_resolution(self, tmp_path):
        document = tmp_path / "remote.yaml"
        document.write_text(
            """openapi: 3.0.0
info: {title: Remote, version: 1.0.0}
paths:
  /remote:
    post:
      requestBody:
        $ref: 'https://example.com/components.yaml#/requestBodies/Remote'
      responses: {'204': {description: OK}}
""",
            encoding="utf-8",
        )

        endpoint = parse_openapi(document)[0]

        assert endpoint.request_body == {
            "$ref": "https://example.com/components.yaml#/requestBodies/Remote"
        }


class TestSwagger2Parser:
    def test_parses_body_parameters_and_security_inheritance(self):
        endpoints = parse_openapi(FIXTURES / "swagger2.yaml")
        update = next(
            endpoint for endpoint in endpoints if endpoint.operation_id == "updateUser"
        )

        assert update.auth_required is True
        assert update.request_body_required is True
        assert update.content_type == "application/json"
        assert update.request_body["required"] == ["name"]
        assert (
            update.responses["200"]["schema"]["properties"]["id"]["type"] == "integer"
        )

    def test_parses_form_data_and_file_schema(self):
        endpoints = parse_openapi(FIXTURES / "swagger2.yaml")
        upload = next(
            endpoint for endpoint in endpoints if endpoint.operation_id == "uploadFile"
        )

        assert upload.content_type == "multipart/form-data"
        assert upload.request_body_required is True
        assert upload.request_body["properties"]["file"] == {
            "type": "string",
            "format": "binary",
        }
        assert upload.request_body["properties"]["note"]["maxLength"] == 200

    def test_empty_operation_security_disables_root_security(self):
        endpoints = parse_openapi(FIXTURES / "swagger2.yaml")
        get_user = next(
            endpoint for endpoint in endpoints if endpoint.operation_id == "getUser"
        )

        assert get_user.auth_required is False
        assert get_user.parameters[0].constraints["format"] == "int64"
        assert (
            get_user.responses["404"]["schema"]["properties"]["message"]["type"]
            == "string"
        )
