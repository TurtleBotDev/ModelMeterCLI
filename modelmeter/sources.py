"""Additional Copilot usage sources beyond VS Code chat session files."""

from __future__ import annotations

import hashlib
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import vscode_user_dir
from .models import PricingFile, RequestUsage
from .pricing import estimate_credits, read_number
from .sessions import walk

AI_CREDIT_MARKER = '"copilotUsageNanoAiu"'
SUPPORTED_USAGE_EXTENSIONS = {".json", ".jsonl"}
USAGE_FOLDER_NAMES = {
    "github.copilot-chat",
    "debug-logs",
    "transcripts",
    "chatsessions",
    "emptywindowchatsessions",
}
IGNORED_USAGE_FILES = {"settingembeddings.json", "commandembeddings.json"}
MAX_USAGE_FILE_SIZE_BYTES = 200 * 1024 * 1024
MAX_SCAN_DEPTH = 12


def platform_vscode_user_dirs() -> list[Path]:
    """Return likely VS Code and VS Code Insiders user directories."""

    home = Path.home()
    system = platform.system()
    if system == "Windows":
        app_data = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        return [app_data / "Code" / "User", app_data / "Code - Insiders" / "User"]
    if system == "Darwin":
        base = home / "Library" / "Application Support"
        return [base / "Code" / "User", base / "Code - Insiders" / "User"]
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    return [config_home / "Code" / "User", config_home / "Code - Insiders" / "User"]


def vscode_usage_roots(workspace_storage: Path, extra_paths: Iterable[Path] = ()) -> list[Path]:
    """Return existing VS Code roots that may contain Copilot usage logs."""

    candidates: list[Path] = []
    for user_dir in platform_vscode_user_dirs():
        candidates.extend([user_dir / "globalStorage", user_dir / "workspaceStorage"])
    candidates.extend([vscode_user_dir() / "globalStorage", workspace_storage])
    if workspace_storage.name == "workspaceStorage":
        candidates.append(workspace_storage.parent / "globalStorage")
    candidates.extend(extra_paths)
    return unique_existing_paths(candidates)


def copilot_cli_roots(copilot_home: Path) -> list[Path]:
    """Return existing Copilot CLI roots that may contain usage events."""

    return unique_existing_paths([copilot_home / "session-state", copilot_home / "logs"])


def unique_existing_paths(paths: Iterable[Path]) -> list[Path]:
    """Return unique existing paths in their first-seen order."""

    seen: set[Path] = set()
    existing: list[Path] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        existing.append(resolved)
    return existing


def path_contains_usage_folder(path: Path) -> bool:
    """Return whether a path includes a known Copilot usage folder name."""

    return any(part.lower() in USAGE_FOLDER_NAMES for part in path.parts)


def scan_usage_files(roots: Iterable[Path], include_all_supported: bool = False) -> list[Path]:
    """Find supported usage files below roots without scanning unbounded trees."""

    files: list[Path] = []
    for root in unique_existing_paths(roots):
        files.extend(scan_usage_folder(root, 0, path_contains_usage_folder(root), include_all_supported))
    return sorted(set(files))


def scan_usage_folder(root: Path, depth: int, inside_usage_folder: bool, include_all_supported: bool) -> list[Path]:
    """Recursively scan one folder for JSON and JSONL usage files."""

    if depth > MAX_SCAN_DEPTH:
        return []
    try:
        entries = list(root.iterdir())
    except OSError:
        return []

    files: list[Path] = []
    for entry in entries:
        try:
            if entry.is_dir():
                files.extend(
                    scan_usage_folder(
                        entry,
                        depth + 1,
                        inside_usage_folder or entry.name.lower() in USAGE_FOLDER_NAMES,
                        include_all_supported,
                    )
                )
                continue
            if not entry.is_file():
                continue
            if entry.name.lower() in IGNORED_USAGE_FILES:
                continue
            if entry.suffix.lower() not in SUPPORTED_USAGE_EXTENSIONS:
                continue
            if not include_all_supported and not inside_usage_folder:
                continue
            if entry.stat().st_size > MAX_USAGE_FILE_SIZE_BYTES:
                continue
            files.append(entry)
        except OSError:
            continue
    return files


def file_contains_text(path: Path, needle: str) -> bool:
    """Return whether a text file contains a marker string."""

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for chunk in iter(lambda: handle.read(4096), ""):
                if needle in chunk:
                    return True
    except OSError:
        return False
    return False


def parse_usage_items(path: Path) -> Iterator[tuple[Any, int]]:
    """Yield JSON values from JSON or JSONL usage files with item indexes."""

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    if path.suffix.lower() == ".jsonl":
        for index, line in enumerate(content.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line), index
            except json.JSONDecodeError:
                continue
        return
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return
    if isinstance(parsed, list):
        for index, item in enumerate(parsed):
            yield item, index
        return
    if isinstance(parsed, dict):
        for key in ("records", "items", "requests", "turns", "chats"):
            values = parsed.get(key)
            if isinstance(values, list):
                for index, item in enumerate(values):
                    yield item, index
                return
    yield parsed, 0


def read_string(record: dict[str, Any], keys: Iterable[str]) -> str | None:
    """Read the first non-empty string from a record."""

    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def read_integer(record: dict[str, Any], keys: Iterable[str]) -> int | None:
    """Read the first non-negative integer-like number from a record."""

    for key in keys:
        if key not in record:
            continue
        value = record.get(key)
        if not isinstance(value, (int, float)):
            continue
        number = read_number(value)
        if number >= 0 and float(number).is_integer():
            return int(number)
    return None


def read_timestamp_any(value: Any) -> datetime | None:
    """Read an ISO timestamp string or epoch value into local time."""

    if isinstance(value, str) and value:
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).astimezone()
        except ValueError:
            return None
    number = read_number(value)
    if number <= 0:
        return None
    if number > 10_000_000_000:
        number = number / 1000
    return datetime.fromtimestamp(number, tz=timezone.utc).astimezone()


def read_timestamp_from_record(record: dict[str, Any], fallback: datetime) -> datetime:
    """Read a timestamp from common usage record fields."""

    for key in ("timestamp", "createdAt", "completedAt", "creationDate", "date", "time", "ts"):
        timestamp = read_timestamp_any(record.get(key))
        if timestamp is not None:
            return timestamp
    return fallback


def subtract_cached_tokens(input_tokens: int, output_tokens: int, cached_tokens: int) -> tuple[int, int]:
    """Remove cached tokens from effective input/output token counts."""

    input_after_cache = max(0, input_tokens - cached_tokens)
    remaining_cached = max(0, cached_tokens - input_tokens)
    output_after_cache = max(0, output_tokens - remaining_cached)
    return input_after_cache, output_after_cache


def stable_fallback_id(path: Path, index: int, record: dict[str, Any]) -> str:
    """Build a stable identifier for records that do not expose an ID."""

    payload = json.dumps(record, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{path}:{index}:{payload}".encode("utf-8")).hexdigest()[:24]
    return f"{path.name}:{index}:{digest}"


def build_usage_from_record(
    record: dict[str, Any],
    path: Path,
    index: int,
    pricing_file: PricingFile,
    source: str,
    workspace: str,
) -> RequestUsage | None:
    """Build a request usage record from Copilot debug-style token fields."""

    attrs = record.get("attrs") if isinstance(record.get("attrs"), dict) else record
    nano_aiu = read_integer(attrs, ("copilotUsageNanoAiu", "copilot_usage_nano_aiu"))
    input_tokens = read_integer(attrs, ("inputTokens", "input_tokens", "promptTokens", "prompt_tokens"))
    output_tokens = read_integer(attrs, ("outputTokens", "output_tokens", "completionTokens", "completion_tokens"))
    if nano_aiu is None and input_tokens is None and output_tokens is None:
        return None
    if input_tokens is None and output_tokens is None:
        return None

    cached_tokens = read_integer(attrs, ("cachedTokens", "cached_tokens", "cachedInputTokens", "cached_input_tokens")) or 0
    cache_write_tokens = (
        read_integer(
            attrs,
            (
                "cacheWriteInputTokens",
                "cache_write_input_tokens",
                "cacheCreationInputTokens",
                "cache_creation_input_tokens",
            ),
        )
        or 0
    )
    effective_input, effective_output = subtract_cached_tokens(input_tokens or 0, output_tokens or 0, cached_tokens)
    model = read_string(attrs, ("model", "resolvedModel", "model_name")) or "unknown"
    response_id = (
        read_string(record, ("responseId", "requestId", "sid", "sessionId", "id"))
        or read_string(attrs, ("responseId", "requestId", "sessionId", "id"))
        or stable_fallback_id(path, index, record)
    )
    timestamp = read_timestamp_from_record(record, datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone())
    recorded_credits = nano_aiu / 1_000_000_000 if nano_aiu and nano_aiu > 0 else None
    estimate, match = estimate_credits(
        {
            "model": model,
            "input_tokens": effective_input,
            "cached_input_tokens": cached_tokens,
            "cache_write_tokens": cache_write_tokens,
            "output_tokens": effective_output,
        },
        pricing_file,
    )
    return RequestUsage(
        response_id=response_id,
        model=model,
        workspace=workspace,
        timestamp=timestamp,
        input_tokens=effective_input,
        cached_input_tokens=cached_tokens,
        cache_write_tokens=cache_write_tokens,
        output_tokens=effective_output,
        recorded_credits=recorded_credits,
        estimated_credits=estimate,
        pricing_match=match,
        source=source,
    )


def collect_vscode_debug_usage(workspace_storage: Path, extra_paths: Iterable[Path], pricing_file: PricingFile) -> tuple[list[RequestUsage], int]:
    """Collect usage from VS Code Copilot debug log JSON and JSONL files."""

    requests: list[RequestUsage] = []
    files = scan_usage_files(vscode_usage_roots(workspace_storage, extra_paths))
    for path in files:
        if not file_contains_text(path, "copilotUsageNanoAiu"):
            continue
        for item, index in parse_usage_items(path):
            for record in walk(item):
                if record.get("type") != "llm_request":
                    continue
                usage = build_usage_from_record(record, path, index, pricing_file, "vscode-debug-log", workspace_from_path(path))
                if usage is not None and usage.recorded_credits is not None:
                    requests.append(usage)
    return requests, len(files)


def collect_copilot_cli_usage(copilot_home: Path, pricing_file: PricingFile) -> tuple[list[RequestUsage], int]:
    """Collect usage from Copilot CLI session-state and log files."""

    roots = copilot_cli_roots(copilot_home)
    files = scan_usage_files(roots, include_all_supported=True)
    requests: list[RequestUsage] = []
    for path in files:
        if path.suffix.lower() not in SUPPORTED_USAGE_EXTENSIONS:
            continue
        for item, index in parse_usage_items(path):
            for record in walk(item):
                usage = build_usage_from_record(record, path, index, pricing_file, "copilot-cli", workspace_from_cli_path(path, copilot_home))
                if usage is not None:
                    requests.append(usage)
    return requests, len(files)


def workspace_from_path(path: Path) -> str:
    """Return a readable workspace/source name from a usage file path."""

    parts = list(path.parts)
    for folder in ("workspaceStorage", "workspace-storage"):
        if folder in parts:
            index = parts.index(folder)
            if index + 1 < len(parts):
                return parts[index + 1]
    return "VS Code"


def workspace_from_cli_path(path: Path, copilot_home: Path) -> str:
    """Return a readable workspace/source name for Copilot CLI usage."""

    try:
        relative = path.relative_to(copilot_home)
    except ValueError:
        return "Copilot CLI"
    parts = relative.parts
    if len(parts) >= 2 and parts[0] == "session-state":
        return f"CLI {parts[1]}"
    return "Copilot CLI"
