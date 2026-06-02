"""Text rendering helpers for summaries, tables, and JSON output."""

from __future__ import annotations

import contextlib
import io
import json
import platform
import sys
from typing import Any, Callable

from .constants import AMBER, ANSI_RE, BOLD, BYLINE, CYAN, DIM, GREEN, LOGO, RED, RESET
from .models import Periods, PricingFile, Summary, Totals


def fmt_number(value: float | int, digits: int = 1) -> str:
    """Format a number with thousands separators and compact decimals."""

    if isinstance(value, float):
        return f"{value:,.{digits}f}".rstrip("0").rstrip(".")
    return f"{value:,}"


def rows_from_map(values: dict[str, Totals], key: str = "credits") -> list[tuple[str, Totals]]:
    """Return totals map entries sorted by credits or total tokens descending."""

    value_reader = (lambda item: item.credits) if key == "credits" else (lambda item: item.total_tokens)
    return sorted(values.items(), key=lambda item: value_reader(item[1]), reverse=True)


def print_kv(label: str, value: str) -> None:
    """Print a left-aligned key/value row."""

    print(f"{label:<18} {value}")


def safe_print(text: str = "") -> None:
    """Print text after replacing characters unsupported by stdout encoding."""

    encoding = sys.stdout.encoding or "utf-8"
    print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def kv_line(label: str, value: str) -> str:
    """Render a left-aligned key/value row."""

    return f"{label:<18} {value}"


def strip_ansi(value: str) -> str:
    """Remove ANSI SGR escape sequences from text."""

    return ANSI_RE.sub("", value)


def visible_len(value: str) -> int:
    """Return printable character count after removing ANSI sequences."""

    return len(strip_ansi(value))


def pad_ansi(value: str, width: int) -> str:
    """Right-pad text using visible length rather than raw ANSI length."""

    return value + " " * max(0, width - visible_len(value))


def colorize(value: str, color: str, enabled: bool = True) -> str:
    """Wrap text in ANSI color when color output is enabled."""

    return f"{color}{value}{RESET}" if enabled else value


def enable_windows_ansi() -> bool:
    """Enable ANSI color handling on modern Windows terminals."""

    if platform.system() != "Windows":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def should_use_color(disabled: bool = False) -> bool:
    """Return whether stdout supports color for this run."""

    import os

    if disabled or os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty() or os.environ.get("TERM") == "dumb":
        return False
    return enable_windows_ansi()


def boxed(lines: list[str]) -> str:
    """Render lines inside a single-width terminal box."""

    width = max(visible_len(line) for line in lines) if lines else 0
    top = "┌" + "─" * (width + 2) + "┐"
    bottom = "└" + "─" * (width + 2) + "┘"
    body = [f"│ {pad_ansi(line, width)} │" for line in lines]
    return "\n".join([top, *body, bottom])


def print_bar(label: str, value: float, total: float, width: int = 26) -> None:
    """Print an ASCII proportional bar."""

    ratio = 0 if total <= 0 else min(1, value / total)
    filled = round(ratio * width)
    print(f"{label:<22} [{'#' * filled}{'.' * (width - filled)}] {fmt_number(value)}")


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    """Print a fixed-width table."""

    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)))


def unknown_model_snippet(model: str) -> str:
    """Return a pricing JSON snippet for an unknown model."""

    return json.dumps(
        {
            model: {
                "input": 2.5,
                "cachedInput": 0.25,
                "cacheWrite": 3.125,
                "output": 15,
            }
        },
        indent=2,
    )


def summary_lines(summary: Summary, periods: Periods, budget: int, pricing_file: PricingFile, color: bool = False) -> list[str]:
    """Render the key summary rows shown by summary and watch views."""

    balance = periods.usage_balance
    state = "under pace" if balance >= 0 else "over pace"
    pace_color = GREEN if balance >= 0 else RED
    remaining = budget - periods.current.credits
    lines = [
        kv_line("Pace", colorize(f"{fmt_number(abs(balance))} credits {state}", pace_color, color)),
        kv_line("Current used", f"{fmt_number(periods.current.credits)} AI credits"),
        kv_line("Expected now", f"{fmt_number(periods.expected_credits)} AI credits"),
        kv_line("Projected end", colorize(f"{fmt_number(periods.projected_credits)} AI credits", GREEN if periods.projected_credits <= budget else RED, color)),
        kv_line("Burn rate", f"{fmt_number(periods.burn_rate_per_day)} credits/day"),
        kv_line("Remaining", colorize(f"{fmt_number(remaining)} of {fmt_number(budget)}", GREEN if remaining >= 0 else RED, color)),
        kv_line("Reset in", f"{periods.days_remaining} day(s)"),
        kv_line("Period", f"{periods.current_start.date()} to {periods.current_end.date()}"),
        kv_line("Previous period", f"{fmt_number(periods.previous.credits)} AI credits"),
        kv_line("All time scanned", f"{fmt_number(periods.all_time.credits)} AI credits"),
        kv_line("Session files", str(summary.files)),
        kv_line("Pricing", f"{pricing_file.path} ({pricing_file.version})"),
    ]
    if pricing_file.error:
        lines.append(kv_line("Pricing error", pricing_file.error))
    if summary.unknown_models:
        lines.extend(["", colorize(f"Unknown models: {', '.join(sorted(summary.unknown_models))}", AMBER, color)])
    return lines


def render_plain_summary(summary: Summary, periods: Periods, budget: int, pricing_file: PricingFile) -> str:
    """Render summary rows without the logo box."""

    return "\n".join(summary_lines(summary, periods, budget, pricing_file))


def print_summary(summary: Summary, periods: Periods, budget: int, pricing_file: PricingFile, color: bool = False) -> None:
    """Print the boxed summary view."""

    logo = [colorize(line, CYAN, color) for line in LOGO]
    lines = [*logo, colorize(BYLINE, DIM, color), "", *summary_lines(summary, periods, budget, pricing_file, color)]
    safe_print(boxed(lines))


def print_watch(summary: Summary, periods: Periods, budget: int, pricing_file: PricingFile, interval: int, color: bool = False) -> None:
    """Print one passive dashboard frame."""

    print_summary(summary, periods, budget, pricing_file, color)
    print()
    safe_print(colorize("Models (current)", BOLD, color))
    safe_print(colorize("----------------", DIM, color))
    for model, usage in rows_from_map(periods.current.models)[:5]:
        print_kv(model[:18], f"{fmt_number(usage.credits)} credits, {fmt_number(usage.total_tokens, 0)} tokens")
    print()
    safe_print(colorize(f"Refreshing every {interval}s. Press Ctrl+C to stop.", DIM, color))


def print_model_credit_bars(totals: Totals) -> None:
    """Print the top model credit totals as bars."""

    credit_rows = rows_from_map(totals.models, "credits")[:8]
    total_credits = sum(usage.credits for _, usage in credit_rows)
    print("AI credits by model")
    print("-------------------")
    if not credit_rows:
        print("No model data yet.")
        return
    for model, usage in credit_rows:
        print_bar(model[:22], usage.credits, total_credits)


def print_models(totals: Totals, title: str) -> None:
    """Print model-level usage totals."""

    print(title)
    print("=" * len(title))
    print_model_credit_bars(totals)
    print()
    rows = []
    for model, usage in rows_from_map(totals.models):
        rows.append(
            [
                model,
                fmt_number(usage.credits),
                fmt_number(usage.input_tokens, 0),
                fmt_number(usage.cached_input_tokens, 0),
                fmt_number(usage.cache_write_tokens, 0),
                fmt_number(usage.output_tokens, 0),
                fmt_number(usage.total_tokens, 0),
                str(usage.requests),
            ]
        )
    print_table(["Model", "AI Credits", "Input", "Cached", "Cache Write", "Output", "Total", "Req"], rows)


def print_workspaces(totals: Totals, title: str) -> None:
    """Print workspace-level usage totals."""

    print(title)
    print("=" * len(title))
    rows = []
    for workspace, usage in rows_from_map(totals.workspaces):
        rows.append(
            [
                workspace,
                fmt_number(usage.credits),
                fmt_number(usage.input_tokens, 0),
                fmt_number(usage.cached_input_tokens, 0),
                fmt_number(usage.cache_write_tokens, 0),
                fmt_number(usage.output_tokens, 0),
                fmt_number(usage.total_tokens, 0),
                str(usage.requests),
            ]
        )
    print_table(["Workspace", "AI Credits", "Input", "Cached", "Cache Write", "Output", "Total", "Req"], rows)


def captured_output(callback: Callable[..., None], *args: Any) -> str:
    """Return stdout emitted by a callback."""

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        callback(*args)
    return buffer.getvalue().rstrip()


def render_unknown(summary: Summary) -> str:
    """Render pricing snippets for every unknown model."""

    if not summary.unknown_models:
        return "No unknown models."
    return "\n\n".join(unknown_model_snippet(model) for model in sorted(summary.unknown_models))


def render_paths(workspace_storage: object, pricing_path: object, settings_path: object) -> str:
    """Render the important filesystem paths used by the app."""

    return "\n".join(
        [
            kv_line("Workspace storage", str(workspace_storage)),
            kv_line("Pricing file", str(pricing_path)),
            kv_line("Settings file", str(settings_path)),
        ]
    )


def to_json(summary: Summary, periods: Periods, budget: int, reset_day: int, pricing_file: PricingFile) -> str:
    """Render machine-readable summary output."""

    def totals_dict(total: Totals) -> dict[str, Any]:
        """Convert aggregate totals to JSON-serializable data."""

        return {
            "requests": total.requests,
            "credits": total.credits,
            "inputTokens": total.input_tokens,
            "cachedInputTokens": total.cached_input_tokens,
            "cacheWriteTokens": total.cache_write_tokens,
            "outputTokens": total.output_tokens,
            "totalTokens": total.total_tokens,
            "unknownModels": sorted(total.unknown_models),
            "models": {name: totals_dict(value) for name, value in total.models.items()},
            "workspaces": {name: totals_dict(value) for name, value in total.workspaces.items()},
            "dailyCredits": total.daily_credits,
        }

    return json.dumps(
        {
            "budget": budget,
            "resetDay": reset_day,
            "pricingPath": str(pricing_file.path),
            "pricingVersion": pricing_file.version,
            "files": summary.files,
            "sessionsWithUsage": summary.sessions_with_usage,
            "currentPeriod": {
                "start": periods.current_start.isoformat(),
                "end": periods.current_end.isoformat(),
                "expectedCredits": periods.expected_credits,
                "usageBalance": periods.usage_balance,
                "burnRatePerDay": periods.burn_rate_per_day,
                "projectedCredits": periods.projected_credits,
                "daysRemaining": periods.days_remaining,
                "usage": totals_dict(periods.current),
            },
            "previousPeriod": totals_dict(periods.previous),
            "allTime": totals_dict(periods.all_time),
        },
        indent=2,
    )
