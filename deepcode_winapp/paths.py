from __future__ import annotations

import sys
from pathlib import Path


APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parent
DATA_DIR = APP_ROOT / "data"
SETTINGS_PATH = DATA_DIR / "settings.json"
SESSIONS_DIR = DATA_DIR / "sessions"
LOGS_DIR = DATA_DIR / "logs"
DIAGNOSTICS_LOG = LOGS_DIR / "diagnostics.log"
