"""Discovery and parsing for VS Code Copilot Chat session files."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote

from .models import PricingFile, RequestUsage, SessionFile, Summary, Totals
from .pricing import canonical_model_name, estimate_credits, read_number


def read_json_or_jsonl(path: Path) -> list[Any]:
    """Read a JSON or JSON Lines file, skipping malformed JSONL lines."""

    content = path.read_text(encoding="utf-8", errors="replace")
    try:
        return [json.loads(content)]
    except json.JSONDecodeError:
        values = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                values.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return values


def walk(value: Any) -> Iterator[dict[str, Any]]:
    """Yield every dictionary nested inside a JSON-like value."""

    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from walk(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk(nested)


def read_model_from_details(details: Any) -> str | None:
    """Extract the model name from Copilot's human-readable details string."""

    return details.split("•")[0].strip() if isinstance(details, str) and details.strip() else None


def read_credits_from_details(details: Any) -> float | None:
    """Extract recorded AI credits from Copilot's details string."""

    if not isinstance(details, str):
        return None
    match = re.search(r"([0-9.]+)\s*credits", details, re.IGNORECASE)
    return float(match.group(1)) if match else None


def read_timestamp(record: dict[str, Any], fallback: datetime) -> datetime:
    """Read a usage timestamp, accepting seconds or milliseconds since epoch."""

    timestamp = max(
        read_number(record.get("completedAt")),
        read_number(record.get("creationDate")),
        read_number(record.get("timestamp")),
    )
    if timestamp <= 0:
        return fallback
    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone()


def read_system_percent(prompt_token_details: Any) -> float:
    """Return the percentage of prompt tokens categorized as system prompt."""

    if not isinstance(prompt_token_details, list):
        return 0.0
    total = 0.0
    for item in prompt_token_details:
        if isinstance(item, dict) and item.get("category") == "System":
            total += read_number(item.get("percentageOfPrompt"))
    return max(0.0, min(100.0, total))


def read_workspace_name(workspace_storage: Path, workspace_id: str) -> str:
    """Read a friendly workspace name from VS Code's workspace metadata."""

    try:
        parsed = json.loads((workspace_storage / workspace_id / "workspace.json").read_text(encoding="utf-8"))
        folder = unquote(str(parsed.get("folder", "")))
        name = re.sub(r"^file:/+", "", folder).rstrip("/\\").split("/")[-1].split("\\")[-1]
        return name or workspace_id
    except (OSError, json.JSONDecodeError):
        return workspace_id


def find_chat_session_files(storage: Path) -> list[SessionFile]:
    """Find JSON and JSONL Copilot Chat session files in workspace storage."""

    files: list[SessionFile] = []
    if not storage.exists():
        return files
    for workspace_dir in storage.iterdir():
        chat_dir = workspace_dir / "chatSessions"
        if not chat_dir.is_dir():
            continue
        workspace_name = read_workspace_name(storage, workspace_dir.name)
        for child in chat_dir.iterdir():
            if child.suffix in {".json", ".jsonl"}:
                files.append(SessionFile(path=child, workspace_id=workspace_dir.name, workspace_name=workspace_name))
    return files


def collect_session_usage(session_file: SessionFile, pricing_file: PricingFile) -> list[RequestUsage]:
    """Parse a session file into deduplicated per-response usage records."""

    fallback_time = datetime.fromtimestamp(session_file.path.stat().st_mtime, tz=timezone.utc).astimezone()
    raw_requests: dict[str, dict[str, Any]] = {}
    credits_by_response_id: dict[str, float] = {}

    try:
        roots = read_json_or_jsonl(session_file.path)
    except OSError:
        return []

    for root in roots:
        for record in walk(root):
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
            response_id = record.get("responseId") or metadata.get("responseId")
            if not isinstance(response_id, str):
                continue

            recorded_credits = read_credits_from_details(record.get("details"))
            if recorded_credits is not None:
                credits_by_response_id[response_id] = recorded_credits

            prompt_tokens = int(read_number(usage.get("promptTokens", record.get("promptTokens"))))
            output_tokens = int(read_number(usage.get("completionTokens", record.get("outputTokens"))))
            if prompt_tokens == 0 and output_tokens == 0:
                continue

            model = (
                record.get("resolvedModel")
                or metadata.get("resolvedModel")
                or read_model_from_details(record.get("details"))
                or "unknown"
            )
            system_percent = read_system_percent(usage.get("promptTokenDetails"))
            cacheable_input_tokens = round(prompt_tokens * system_percent / 100)
            raw_requests[response_id] = {
                "response_id": response_id,
                "model": str(model),
                "workspace": session_file.workspace_name,
                "timestamp": read_timestamp(record, fallback_time),
                "input_tokens": max(0, prompt_tokens - cacheable_input_tokens),
                "cacheable_input_tokens": cacheable_input_tokens,
                "output_tokens": output_tokens,
            }

    return build_request_usage(raw_requests, credits_by_response_id, pricing_file)


def build_request_usage(
    raw_requests: dict[str, dict[str, Any]],
    credits_by_response_id: dict[str, float],
    pricing_file: PricingFile,
) -> list[RequestUsage]:
    """Build typed usage records and infer first-use cache writes per workspace/model."""

    cache_seen_by_model: set[str] = set()
    requests: list[RequestUsage] = []
    for request in sorted(raw_requests.values(), key=lambda item: item["timestamp"]):
        model_key = f"{request['workspace']}:{canonical_model_name(request['model'])}"
        cacheable = int(request["cacheable_input_tokens"])
        cache_write_tokens = cacheable if cacheable > 0 and model_key not in cache_seen_by_model else 0
        cached_input_tokens = cacheable if cacheable > 0 and model_key in cache_seen_by_model else 0
        if cacheable > 0:
            cache_seen_by_model.add(model_key)
        estimate, match = estimate_credits(
            {
                "model": request["model"],
                "input_tokens": request["input_tokens"],
                "cached_input_tokens": cached_input_tokens,
                "cache_write_tokens": cache_write_tokens,
                "output_tokens": request["output_tokens"],
            },
            pricing_file,
        )
        requests.append(
            RequestUsage(
                response_id=request["response_id"],
                model=request["model"],
                workspace=request["workspace"],
                timestamp=request["timestamp"],
                input_tokens=request["input_tokens"],
                cached_input_tokens=cached_input_tokens,
                cache_write_tokens=cache_write_tokens,
                output_tokens=request["output_tokens"],
                recorded_credits=credits_by_response_id.get(request["response_id"]),
                estimated_credits=estimate,
                pricing_match=match,
            )
        )
    return requests


def add_to_breakdowns(total: Totals, request: RequestUsage) -> None:
    """Add request usage to top-level, model, workspace, and daily totals."""

    total.add(request)
    total.models.setdefault(request.model, Totals()).add(request)
    total.workspaces.setdefault(request.workspace, Totals()).add(request)
    day = request.timestamp.date().isoformat()
    total.daily_credits[day] = total.daily_credits.get(day, 0.0) + request.credits


def summarize(files: list[SessionFile], pricing_file: PricingFile) -> Summary:
    """Summarize usage across all discovered session files."""

    summary = Summary(files=len(files))
    for session_file in files:
        requests = collect_session_usage(session_file, pricing_file)
        if requests:
            summary.sessions_with_usage += 1
        for request in requests:
            summary.requests_list.append(request)
            add_to_breakdowns(summary, request)
    return summary
