"""Unified data models for parsed API documentation.

All parsers (Swagger, Postman, Markdown) convert their input
into these standard models for downstream processing.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class Param(BaseModel):
    """A single API parameter (query, path, header, or cookie)."""

    name: str
    location: str  # query / path / header / cookie
    required: bool = False
    param_type: str = "string"  # string / integer / boolean / array / object
    description: str = ""
    constraints: dict[str, Any] = Field(default_factory=dict)
    example: Any | None = None


class ApiEndpoint(BaseModel):
    """A single API endpoint with all its metadata."""

    method: str  # GET / POST / PUT / DELETE / PATCH
    path: str  # /api/users/{id}
    summary: str = ""
    description: str = ""
    operation_id: str = ""
    parameters: list[Param] = Field(default_factory=list)
    request_body: dict[str, Any] | None = None
    request_body_required: bool = False
    responses: dict[str, dict[str, Any]] = Field(default_factory=dict)
    auth_required: bool = False
    tags: list[str] = Field(default_factory=list)
    content_type: str = "application/json"
    content_types: list[str] = Field(default_factory=list)

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        return value.upper()

    @field_validator("path")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        if not value:
            return "/"
        return value if value.startswith("/") else f"/{value}"

    @model_validator(mode="after")
    def synchronize_content_types(self):
        if self.content_types:
            self.content_type = self.content_types[0]
        else:
            self.content_types = [self.content_type]
        return self
