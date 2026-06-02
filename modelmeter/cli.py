"""Command-line entry points for ModelMeter."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .config import apply_settings, copilot_home_dir, default_pricing_path, default_settings_path, workspace_storage_dir
from .constants import DEFAULT_BUDGET, DEFAULT_RESET_DAY
from .menu import run_menu
from .models import Periods, PricingFile, Summary, Totals
from .periods import build_periods, period_totals
from .pricing import ensure_pricing_file, read_pricing_file
from .render import print_kv, print_models, print_summary, print_watch, print_workspaces, should_use_color, to_json, unknown_model_snippet
from .sessions import collect_session_usage, find_chat_session_files, summarize_requests
from .sources import collect_copilot_cli_usage, collect_vscode_debug_usage


def snapshot(args: argparse.Namespace) -> tuple[Summary, Periods, Totals, PricingFile]:
    """Read current files and build all derived reporting objects."""

    current_pricing = read_pricing_file(args.pricing.expanduser())
    chat_files = find_chat_session_files(args.workspace_storage.expanduser())
    chat_requests = []
    chat_sessions_with_usage = 0
    for session_file in chat_files:
        session_requests = collect_session_usage(session_file, current_pricing)
        if session_requests:
            chat_sessions_with_usage += 1
        chat_requests.extend(session_requests)
    debug_requests, debug_files = collect_vscode_debug_usage(args.workspace_storage.expanduser(), [path.expanduser() for path in args.data_path], current_pricing)
    cli_requests, cli_files = collect_copilot_cli_usage(args.copilot_home.expanduser(), current_pricing)
    summary = summarize_requests(
        [*chat_requests, *debug_requests, *cli_requests],
        files=len(chat_files) + debug_files + cli_files,
        sessions_with_usage=chat_sessions_with_usage,
    )
    periods = build_periods(summary, args.budget, args.reset_day)
    totals = period_totals(periods, args.period)
    return summary, periods, totals, current_pricing


def run_watch(args: argparse.Namespace) -> int:
    """Run the passive auto-refreshing dashboard."""

    try:
        while True:
            summary, periods, _, current_pricing = snapshot(args)
            if not args.no_clear:
                print("\033[2J\033[H", end="")
            print_watch(summary, periods, args.budget, current_pricing, args.interval, should_use_color(args.no_color))
            sys.stdout.flush()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""

    parser = argparse.ArgumentParser(description="Local Copilot usage meter. No third-party Python packages required.")
    parser.add_argument("command", nargs="?", default="menu", choices=["menu", "watch", "summary", "models", "workspaces", "unknown", "paths", "init-pricing", "json"])
    parser.add_argument("--budget", type=int, default=None, help=f"Monthly AI credit allowance. Saved setting or {DEFAULT_BUDGET}.")
    parser.add_argument("--reset-day", type=int, default=None, help=f"Monthly reset day, 1-31. Saved setting or {DEFAULT_RESET_DAY}.")
    parser.add_argument("--period", choices=["current", "previous", "all"], default="current", help="Period for models/workspaces.")
    parser.add_argument("--interval", type=int, default=30, help="Refresh interval in seconds for menu/watch mode. Default: 30")
    parser.add_argument("--no-clear", action="store_true", help="Do not clear the terminal between watch refreshes.")
    parser.add_argument("--no-color", action="store_true", help="Disable terminal colours.")
    parser.add_argument("--workspace-storage", type=Path, default=workspace_storage_dir(), help="Path to VS Code User/workspaceStorage.")
    parser.add_argument("--copilot-home", type=Path, default=copilot_home_dir(), help="Path to GitHub Copilot CLI home. Defaults to COPILOT_HOME or ~/.copilot.")
    parser.add_argument("--data-path", type=Path, action="append", default=[], help="Extra local folder to scan for Copilot usage JSON/JSONL files.")
    parser.add_argument("--pricing", type=Path, default=default_pricing_path(), help="Path to modelmeter-pricing.json.")
    parser.add_argument("--settings", type=Path, default=default_settings_path(), help="Path to modelmeter-settings.json.")
    return parser


def validate_args(args: argparse.Namespace) -> int:
    """Validate normalized arguments and return a process status."""

    if args.reset_day < 1 or args.reset_day > 31:
        print("--reset-day must be between 1 and 31", file=sys.stderr)
        return 2
    if args.interval < 1:
        print("--interval must be at least 1", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run ModelMeter from command-line arguments."""

    args = build_parser().parse_args(argv)
    apply_settings(args)
    validation_status = validate_args(args)
    if validation_status:
        return validation_status

    if args.command == "init-pricing":
        ensure_pricing_file(args.pricing.expanduser())
        print(args.pricing.expanduser())
        return 0
    if args.command == "paths":
        print_kv("Workspace storage", str(args.workspace_storage.expanduser()))
        print_kv("Copilot home", str(args.copilot_home.expanduser()))
        if args.data_path:
            print_kv("Extra data paths", ", ".join(str(path.expanduser()) for path in args.data_path))
        print_kv("Pricing file", str(args.pricing.expanduser()))
        print_kv("Settings file", str(args.settings.expanduser()))
        return 0

    if args.command == "menu":
        status = run_menu(args, snapshot)
        return run_watch(args) if status == 1 else status
    if args.command == "watch":
        return run_watch(args)

    summary, periods, totals, pricing_file = snapshot(args)
    if args.command == "summary":
        print_summary(summary, periods, args.budget, pricing_file, should_use_color(args.no_color))
    elif args.command == "models":
        print_models(totals, f"Models ({args.period})")
    elif args.command == "workspaces":
        print_workspaces(totals, f"Workspaces ({args.period})")
    elif args.command == "unknown":
        if not summary.unknown_models:
            print("No unknown models.")
        for model in sorted(summary.unknown_models):
            print(unknown_model_snippet(model))
    elif args.command == "json":
        print(to_json(summary, periods, args.budget, args.reset_day, pricing_file))
    return 0
