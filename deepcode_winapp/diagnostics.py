from __future__ import annotations

from datetime import datetime, timezone

from .paths import DIAGNOSTICS_LOG, LOGS_DIR


def append_diagnostic(message: str) -> None:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        with DIAGNOSTICS_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")
    except OSError:
        pass
