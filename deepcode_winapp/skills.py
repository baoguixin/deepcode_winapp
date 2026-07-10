from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .paths import APP_ROOT, PROJECT_ROOT


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    path: str
    body: str
    prompt_document: str
    resources: tuple[str, ...]
    source: str
    allow_implicit_invocation: bool = True


EXCLUDED_RESOURCE_PARTS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".venv",
    "venv",
}


def discover_skills(workspace: str) -> list[SkillInfo]:
    roots = _skill_roots(Path(workspace).expanduser())
    found: dict[str, SkillInfo] = {}
    for source, root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for skill_file in _iter_skill_files(root):
            skill = read_skill(skill_file, source)
            if skill and skill.name not in found:
                found[skill.name] = skill
    return list(found.values())


def read_skill(path: Path, source: str = "Project") -> SkillInfo | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    frontmatter, body = split_frontmatter(raw)
    metadata = parse_frontmatter(frontmatter)
    name = str(metadata.get("name") or path.parent.name).strip().replace("_", "-")
    if not name:
        return None
    description = str(metadata.get("description") or "").strip()
    allow = str(metadata.get("metadata.allow-implicit-invocation") or "true").strip().lower() != "false"
    prompt_document = build_prompt_document(frontmatter, body)
    return SkillInfo(
        name=name,
        description=description,
        path=str(path),
        body=body.strip(),
        prompt_document=prompt_document,
        resources=tuple(list_skill_resources(path.parent)),
        source=source,
        allow_implicit_invocation=allow,
    )


def split_frontmatter(raw: str) -> tuple[str, str]:
    if not raw.startswith("---"):
        return "", raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return "", raw
    return parts[1].strip(), parts[2].strip()


def parse_frontmatter(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    current_parent = ""
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if indent == 0:
            if value:
                result[key] = value
                current_parent = ""
            else:
                current_parent = key
        elif current_parent:
            result[f"{current_parent}.{key}"] = value
    return result


def build_prompt_document(frontmatter: str, body: str) -> str:
    kept_lines: list[str] = []
    skip_metadata_block = False
    for raw_line in frontmatter.splitlines():
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 0 and stripped.startswith("metadata:"):
            skip_metadata_block = True
            continue
        if skip_metadata_block and indent > 0:
            continue
        skip_metadata_block = False
        kept_lines.append(raw_line)
    cleaned_frontmatter = "\n".join(line for line in kept_lines if line.strip())
    if cleaned_frontmatter:
        return f"---\n{cleaned_frontmatter}\n---\n\n{body.strip()}"
    return body.strip()


def list_skill_resources(skill_dir: Path, limit: int = 50) -> list[str]:
    resources: list[str] = []
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or path.name == "SKILL.md":
            continue
        try:
            relative = path.relative_to(skill_dir)
        except ValueError:
            continue
        if any(part in EXCLUDED_RESOURCE_PARTS or part.startswith(".") for part in relative.parts):
            continue
        resources.append(str(relative))
        if len(resources) >= limit:
            break
    return resources


def parse_requested_skill_names(text: str) -> set[str]:
    names: set[str] = set()
    for token in re.findall(r"(?<!\w)[/@$]([A-Za-z0-9][A-Za-z0-9_.-]*)", text):
        lowered = token.lower()
        if lowered not in {"skills", "skill"}:
            names.add(lowered.replace("_", "-"))
    return names


def select_skills(skills: list[SkillInfo], user_text: str, selected_names: list[str] | None, auto_load: bool) -> list[SkillInfo]:
    selected = {name.lower().replace("_", "-") for name in selected_names or []}
    requested = parse_requested_skill_names(user_text)
    text = user_text.lower()
    result: list[SkillInfo] = []
    for skill in skills:
        name = skill.name.lower()
        if name in selected or name in requested:
            result.append(skill)
            continue
        if not auto_load or not skill.allow_implicit_invocation:
            continue
        if name in text or _description_matches(skill.description, text):
            result.append(skill)
    return result


def format_skill_system_message(skills: list[SkillInfo], max_chars_per_skill: int = 12000) -> str:
    if not skills:
        return ""
    sections = [
        "Use the skill documents below to assist the user. Follow these skills when relevant."
    ]
    for skill in skills:
        body = skill.prompt_document[:max_chars_per_skill]
        if len(skill.prompt_document) > max_chars_per_skill:
            body += "\n[skill truncated]"
        resources = ""
        if skill.resources:
            resource_lines = "\n".join(f"- {resource}" for resource in skill.resources)
            resources = f"\n<skill_resources>\n{resource_lines}\n</skill_resources>"
        sections.append(
            f"<{skill.name}-skill source=\"{skill.source}\" path=\"{skill.path}\">\n"
            f"{body}{resources}\n"
            f"</{skill.name}-skill>"
        )
    return "\n\n".join(sections)


def format_skill_list(skills: list[SkillInfo]) -> str:
    if not skills:
        return "No skills found."
    return "\n".join(f"- {skill.name} ({skill.source}): {skill.description or skill.path}" for skill in skills)


def _skill_roots(workspace: Path) -> list[tuple[str, Path]]:
    cli_bundled = PROJECT_ROOT / "deepcode-cli-main" / "packages" / "core" / "templates" / "skills" / "bundled"
    return [
        ("Project", workspace / ".deepcode" / "skills"),
        ("Project", workspace / ".agents" / "skills"),
        ("Project", workspace / ".codex" / "skills"),
        ("User", Path.home() / ".deepcode" / "skills"),
        ("User", Path.home() / ".agents" / "skills"),
        ("User", Path.home() / ".codex" / "skills"),
        ("Bundled", APP_ROOT / "bundled" / "skills"),
        ("Bundled", cli_bundled),
    ]


def _iter_skill_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("SKILL.md")):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in EXCLUDED_RESOURCE_PARTS for part in relative.parts[:-1]):
            continue
        files.append(path)
    return files


def _description_matches(description: str, text: str) -> bool:
    terms = [term for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]{3,}", description.lower())]
    stop = {"when", "with", "from", "this", "that", "using", "skill", "skills", "user", "asks"}
    strong_terms = [term for term in terms if term not in stop]
    matches = [term for term in strong_terms[:20] if term in text]
    return len(set(matches)) >= 2
