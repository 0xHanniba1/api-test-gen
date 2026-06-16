from api_test_gen.generator.naming import (
    assign_endpoint_filenames,
    group_endpoints_by_tag,
)
from api_test_gen.generator.testcase_document import parse_testcase_document
from api_test_gen.parser.base import ApiEndpoint


def _document(*headings: str):
    sections = []
    for index, heading in enumerate(headings, start=1):
        sections.append(
            f"""## {heading}

| 编号 | 场景 | 输入 | 预期状态码 | 预期响应 | 优先级 |
|------|------|------|-----------|---------|--------|
| TC-{index:03d} | ok | 无 | 200 | ok | P0 |"""
        )
    return parse_testcase_document("\n\n".join(sections))


def _endpoint(tag: str) -> ApiEndpoint:
    return ApiEndpoint(method="GET", path=f"/{tag}", tags=[tag])


def test_assign_endpoint_filename_uses_method_and_path():
    document = _document("GET /pets/{petId}")

    filenames = assign_endpoint_filenames(document.sections)

    assert filenames[("GET", "/pets/{petId}")] == "test_get_pets_by_pet_id.py"


def test_assign_endpoint_filename_resolves_slug_collisions_stably():
    first = _document("GET /foo-bar", "GET /foo_bar")
    second = _document("GET /foo_bar", "GET /foo-bar")

    first_names = assign_endpoint_filenames(first.sections)
    second_names = assign_endpoint_filenames(second.sections)

    assert first_names == second_names
    assert len(set(first_names.values())) == 2
    assert all(name.startswith("test_get_foo_bar_") for name in first_names.values())


def test_group_endpoints_by_tag_reuses_name_for_same_raw_tag():
    endpoints = [_endpoint("Admin API"), _endpoint("Admin API")]

    groups = group_endpoints_by_tag(endpoints)

    assert set(groups) == {"admin_api"}
    assert len(groups["admin_api"]) == 2


def test_group_endpoints_by_tag_resolves_normalization_collisions():
    endpoints = [_endpoint("Admin API"), _endpoint("admin-api")]

    groups = group_endpoints_by_tag(endpoints)

    assert len(groups) == 2
    assert all(name.startswith("admin_api_") for name in groups)
