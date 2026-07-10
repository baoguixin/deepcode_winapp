from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


TEXT_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".conf",
    ".csv",
    ".css",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".log",
    ".md",
    ".py",
    ".rst",
    ".sql",
    ".tex",
    ".toml",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class AttachmentPreview:
    path: str
    name: str
    size: int
    content: str
    truncated: bool = False
    readable: bool = True


def build_attachment_context(paths: list[str], max_chars_per_file: int = 12000, max_files: int = 8) -> str:
    previews = [read_attachment_preview(path, max_chars_per_file) for path in paths[:max_files]]
    if not previews:
        return ""

    lines = ["<attachments>"]
    for preview in previews:
        lines.append(
            f'<attachment name="{_escape_attr(preview.name)}" path="{_escape_attr(preview.path)}" '
            f'size="{preview.size}" readable="{str(preview.readable).lower()}">'
        )
        if preview.readable:
            lines.append(preview.content)
            if preview.truncated:
                lines.append("[attachment truncated]")
        else:
            lines.append(
                "Binary or unsupported attachment. Use the file path above if a local tool can open or inspect it."
            )
        lines.append("</attachment>")
    if len(paths) > max_files:
        lines.append(f"[{len(paths) - max_files} additional attachment(s) omitted]")
    lines.append("</attachments>")
    return "\n".join(lines)


def read_attachment_preview(path: str, max_chars: int = 12000) -> AttachmentPreview:
    file_path = Path(path).expanduser()
    stat = file_path.stat()
    readable = _looks_textual(file_path)
    if not readable:
        return AttachmentPreview(str(file_path), file_path.name, stat.st_size, "", readable=False)

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return AttachmentPreview(str(file_path), file_path.name, stat.st_size, "", readable=False)

    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars]
    return AttachmentPreview(str(file_path), file_path.name, stat.st_size, content, truncated=truncated)


def _looks_textual(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    try:
        chunk = path.read_bytes()[:2048]
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    return True


def _escape_attr(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
