from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WorkspaceError(RuntimeError):
    pass


@dataclass
class ToolResult:
    ok: bool
    content: str
    data: dict[str, Any] | None = None


class WorkspaceService:
    def __init__(self, root: str) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.exists():
            raise WorkspaceError(f"Workspace does not exist: {self.root}")
        if not self.root.is_dir():
            raise WorkspaceError(f"Workspace is not a directory: {self.root}")

    def resolve_inside(self, relative_path: str | None = None) -> Path:
        raw = (relative_path or ".").strip() or "."
        candidate = (self.root / raw).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError("Path escapes the workspace.") from exc
        return candidate

    def list_files(self, relative_path: str = ".", pattern: str = "*", max_results: int = 200) -> ToolResult:
        base = self.resolve_inside(relative_path)
        if not base.exists():
            raise WorkspaceError(f"Path not found: {relative_path}")
        if base.is_file():
            return ToolResult(True, str(base.relative_to(self.root)))

        matches: list[str] = []
        limit = max(1, min(int(max_results), 1000))
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "node_modules", ".venv", "venv"}]
            rel_dir = Path(dirpath).resolve().relative_to(self.root)
            for name in filenames:
                rel = rel_dir / name
                if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(str(rel), pattern):
                    matches.append(str(rel))
                    if len(matches) >= limit:
                        content = "\n".join(matches)
                        return ToolResult(True, content, {"truncated": True, "count": len(matches)})
        return ToolResult(True, "\n".join(matches) or "(no files)", {"truncated": False, "count": len(matches)})

    def read_file(self, path: str, max_chars: int = 12000) -> ToolResult:
        file_path = self.resolve_inside(path)
        if not file_path.is_file():
            raise WorkspaceError(f"File not found: {path}")
        text = file_path.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > max_chars
        content = text[:max_chars]
        if truncated:
            content += f"\n\n[truncated: {len(text) - max_chars} chars omitted]"
        return ToolResult(True, content, {"truncated": truncated, "path": str(file_path)})

    def write_file(self, path: str, content: str) -> ToolResult:
        file_path = self.resolve_inside(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return ToolResult(True, f"Wrote {file_path.relative_to(self.root)}", {"path": str(file_path)})

    def replace_in_file(self, path: str, old: str, new: str) -> ToolResult:
        file_path = self.resolve_inside(path)
        if not file_path.is_file():
            raise WorkspaceError(f"File not found: {path}")
        text = file_path.read_text(encoding="utf-8", errors="replace")
        if old not in text:
            raise WorkspaceError("Old text was not found in the file.")
        updated = text.replace(old, new, 1)
        file_path.write_text(updated, encoding="utf-8")
        return ToolResult(True, f"Updated {file_path.relative_to(self.root)}", {"path": str(file_path)})

    def run_powershell(self, command: str, timeout_seconds: int = 30) -> ToolResult:
        if is_dangerous_shell_command(command):
            raise WorkspaceError("Command looks destructive and was blocked by the local policy.")
        timeout = max(1, min(int(timeout_seconds), 600))
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                cwd=str(self.root),
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + ("\n" + exc.stderr if exc.stderr else "")
            return ToolResult(False, _truncate_output(output or "Command timed out.", 12000), {"timed_out": True})
        output = completed.stdout
        if completed.stderr:
            output += ("\n" if output else "") + completed.stderr
        return ToolResult(
            completed.returncode == 0,
            _truncate_output(output or f"(exit code {completed.returncode}, no output)", 12000),
            {"exit_code": completed.returncode},
        )

    def open_path(self, target: str) -> ToolResult:
        cleaned = target.strip()
        if not cleaned:
            raise WorkspaceError("Target path or URL is required.")
        parsed = urllib.parse.urlparse(cleaned)
        if parsed.scheme in {"http", "https"}:
            _open_target(cleaned)
            return ToolResult(True, f"Opened URL: {cleaned}", {"target": cleaned})

        resolved = self.resolve_inside(cleaned)
        if not resolved.exists():
            raise WorkspaceError(f"Path not found: {target}")
        _open_target(str(resolved))
        return ToolResult(True, f"Opened {resolved.relative_to(self.root)}", {"target": str(resolved)})

    def launch_app(self, executable: str, arguments: list[str] | None = None) -> ToolResult:
        cleaned = executable.strip()
        if not cleaned:
            raise WorkspaceError("Executable is required.")
        args = [str(item) for item in (arguments or [])]
        try:
            process = subprocess.Popen([cleaned, *args], cwd=str(self.root))
        except OSError as exc:
            raise WorkspaceError(f"Could not launch application: {exc}") from exc
        return ToolResult(True, f"Launched {cleaned}", {"pid": process.pid, "executable": cleaned, "arguments": args})


def is_dangerous_shell_command(command: str) -> bool:
    normalized = command.strip().lower()
    if "remove-item" in normalized and "-recurse" in normalized:
        return True
    if "git reset" in normalized and "--hard" in normalized:
        return True
    if "git clean" in normalized and "-f" in normalized:
        return True
    patterns = [
        r"\brm\b.*\b-rf\b",
        r"\bdel\b.*\b/s\b",
        r"\bformat-volume\b",
        r"\bdiskpart\b",
        r"\bshutdown\b",
    ]
    return any(re.search(pattern, normalized) for pattern in patterns)


def _truncate_output(output: str, max_chars: int) -> str:
    if len(output) <= max_chars:
        return output
    return output[:max_chars] + f"\n[truncated: {len(output) - max_chars} chars omitted]"


def _open_target(target: str) -> None:
    os.startfile(target)  # type: ignore[attr-defined]
