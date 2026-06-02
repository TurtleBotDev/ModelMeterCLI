"""Filesystem paths and persisted user settings."""

from __future__ import annotations

import argparse
import json
import os
import platform
from pathlib import Path
from typing import Any

from .constants import DEFAULT_BUDGET, DEFAULT_RESET_DAY


def vscode_user_dir() -> Path:
    """Return the platform-specific VS Code user data directory."""

    home = Path.home()
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "Code" / "User"
    if system == "Darwin":
        return home / "Library" / "Application Support" / "Code" / "User"
    return home / ".config" / "Code" / "User"


def workspace_storage_dir() -> Path:
    """Return VS Code's workspace storage directory."""

    return vscode_user_dir() / "workspaceStorage"


def modelmeter_dir() -> Path:
    """Return the directory where ModelMeter keeps settings and pricing."""

    return Path.home() / ".copilot"


def default_pricing_path() -> Path:
    """Return the default pricing file path."""

    return modelmeter_dir() / "modelmeter-pricing.json"


def default_settings_path() -> Path:
    """Return the default settings file path."""

    return modelmeter_dir() / "modelmeter-settings.json"


def read_settings(path: Path) -> dict[str, Any]:
    """Read saved settings, returning an empty dict for missing or invalid files."""

    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def save_settings(path: Path, budget: int, reset_day: int) -> None:
    """Persist budget and reset day settings as JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"budget": budget, "resetDay": reset_day}, indent=2) + "\n",
        encoding="utf-8",
    )


def apply_settings(args: argparse.Namespace) -> None:
    """Fill missing CLI settings from the saved settings file or defaults."""

    settings = read_settings(args.settings.expanduser())
    if args.budget is None:
        budget = settings.get("budget", DEFAULT_BUDGET)
        args.budget = budget if isinstance(budget, int) and budget > 0 else DEFAULT_BUDGET
    if args.reset_day is None:
        reset_day = settings.get("resetDay", DEFAULT_RESET_DAY)
        args.reset_day = reset_day if isinstance(reset_day, int) and 1 <= reset_day <= 31 else DEFAULT_RESET_DAY
