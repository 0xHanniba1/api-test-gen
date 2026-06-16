"""Skill loader — selects and loads test knowledge modules based on endpoint characteristics."""

from pathlib import Path

from api_test_gen.parser.base import ApiEndpoint

SKILLS_DIR = Path(__file__).parent

PAGINATION_PARAM_NAMES = {"page", "size", "limit", "offset", "page_size", "per_page", "pagesize"}


def select_skills(endpoint: ApiEndpoint, depth: str) -> list[str]:
    """Select which skill files to load based on endpoint features and depth."""
    skills = ["base.md"]

    if endpoint.parameters:
        skills.append("param-validation.md")

    if _has_pagination_params(endpoint):
        skills.append("pagination.md")

    if endpoint.content_type == "multipart/form-data":
        skills.append("file-upload.md")

    if depth == "full":
        for s in ("auth-testing.md", "idempotency.md"):
            if s not in skills:
                skills.append(s)

    return skills


def load_skill_content(skill_names: list[str]) -> str:
    """Load and concatenate the content of the given skill files."""
    parts = []
    for name in skill_names:
        path = SKILLS_DIR / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts)


def _has_pagination_params(endpoint: ApiEndpoint) -> bool:
    param_names = {p.name.lower() for p in endpoint.parameters}
    return bool(param_names & PAGINATION_PARAM_NAMES)
