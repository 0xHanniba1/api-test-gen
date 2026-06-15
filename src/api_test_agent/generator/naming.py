"""Deterministic names for generated endpoint and tag artifacts."""

import hashlib
import re
from collections import defaultdict

from api_test_agent.generator.common import normalize_identifier
from api_test_agent.generator.testcase_document import EndpointSection
from api_test_agent.parser.base import ApiEndpoint


def assign_endpoint_filenames(
    sections: tuple[EndpointSection, ...],
) -> dict[tuple[str, str], str]:
    """Assign order-independent flat test filenames to endpoint sections."""
    candidates: dict[tuple[str, str], str] = {}
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for section in sections:
        candidate = f"test_{section.method.lower()}_{_path_slug(section.path)}.py"
        candidates[section.key] = candidate
        groups[candidate].append(section.key)

    result = {}
    for key, candidate in candidates.items():
        if len(groups[candidate]) == 1:
            result[key] = candidate
        else:
            suffix = _short_hash(f"{key[0]} {key[1]}")
            result[key] = f"{candidate[:-3]}_{suffix}.py"
    return result


def group_endpoints_by_tag(
    endpoints: list[ApiEndpoint],
) -> dict[str, list[ApiEndpoint]]:
    """Group endpoints by deterministic, collision-safe normalized tag names."""
    raw_tags = [
        endpoint.tags[0] if endpoint.tags else "default" for endpoint in endpoints
    ]
    normalized_groups: dict[str, set[str]] = defaultdict(set)
    for raw_tag in raw_tags:
        normalized_groups[normalize_identifier(raw_tag)].add(raw_tag)

    safe_names = {}
    for raw_tag in dict.fromkeys(raw_tags):
        normalized = normalize_identifier(raw_tag)
        if len(normalized_groups[normalized]) == 1:
            safe_names[raw_tag] = normalized
        else:
            safe_names[raw_tag] = f"{normalized}_{_short_hash(raw_tag)}"

    groups: dict[str, list[ApiEndpoint]] = {}
    for endpoint, raw_tag in zip(endpoints, raw_tags, strict=True):
        groups.setdefault(safe_names[raw_tag], []).append(endpoint)
    return groups


def _path_slug(path: str) -> str:
    segments = []
    for segment in path.strip("/").split("/"):
        if not segment:
            continue
        match = re.fullmatch(r"\{([^{}]+)\}", segment)
        if match:
            segments.extend(["by", _snake_case(match.group(1))])
        else:
            segments.append(_snake_case(segment))
    return "_".join(filter(None, segments)) or "root"


def _snake_case(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower() or "value"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
