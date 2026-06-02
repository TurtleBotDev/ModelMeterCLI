"""Interactive terminal menu for ModelMeter."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import time
from dataclasses import dataclass, field
from typing import Any

from .config import save_settings
from .constants import BYLINE, CYAN, DIM, GREEN, LOGO, RED
from .models import Periods, PricingFile, Summary
from .periods import period_totals
from .render import captured_output, colorize, fmt_number, print_models, print_workspaces, render_paths, render_plain_summary, render_unknown, safe_print


@dataclass
class MenuItem:
    """One selectable row in the interactive menu tree."""

    title: str
    view: str | None = None
    period: str = "current"
    action: str | None = None
    children: list["MenuItem"] = field(default_factory=list)
    expanded: bool = False


def menu_items() -> list[MenuItem]:
    """Create the default menu tree."""

    return [
        MenuItem("Summary", view="summary"),
        MenuItem(
            "Models",
            children=[
                MenuItem("Current", view="models", period="current"),
                MenuItem("Previous", view="models", period="previous"),
                MenuItem("All Time", view="models", period="all"),
            ],
            expanded=True,
        ),
        MenuItem(
            "Workspaces",
            children=[
                MenuItem("Current", view="workspaces", period="current"),
                MenuItem("Previous", view="workspaces", period="previous"),
                MenuItem("All Time", view="workspaces", period="all"),
            ],
        ),
        MenuItem("Unknown Models", view="unknown"),
        MenuItem(
            "Settings",
            children=[
                MenuItem("View Settings", view="settings"),
                MenuItem("Set Budget", action="set-budget"),
                MenuItem("Set Reset Day", action="set-reset-day"),
            ],
        ),
        MenuItem("Paths", view="paths"),
    ]


def flatten_menu(items: list[MenuItem], depth: int = 0, parent: MenuItem | None = None) -> list[tuple[MenuItem, int, MenuItem | None]]:
    """Flatten visible menu items into rows with depth and parent metadata."""

    rows: list[tuple[MenuItem, int, MenuItem | None]] = []
    for item in items:
        rows.append((item, depth, parent))
        if item.children and item.expanded:
            rows.extend(flatten_menu(item.children, depth + 1, item))
    return rows


def view_title(item: MenuItem) -> str:
    """Return the title shown above the active detail pane."""

    if item.period == "current":
        return item.title
    return f"{item.title} ({item.period})"


def render_settings(args: argparse.Namespace) -> str:
    """Render the settings detail view."""

    from .render import kv_line

    return "\n".join(
        [
            kv_line("Monthly budget", f"{fmt_number(args.budget)} AI credits"),
            kv_line("Reset day", str(args.reset_day)),
            kv_line("Settings file", str(args.settings.expanduser())),
            "",
            "Use Settings > Set Budget or Set Reset Day to save changes.",
            "Command-line flags still override saved settings for that run.",
        ]
    )


def set_runtime_setting(args: argparse.Namespace, action: str, raw_value: str) -> str:
    """Validate, apply, and persist a setting entered in the menu."""

    if not raw_value.strip():
        return "No change."
    try:
        value = int(raw_value.strip())
    except ValueError:
        return "Enter a whole number."

    if action == "set-budget":
        if value <= 0:
            return "Budget must be greater than 0."
        args.budget = value
    elif action == "set-reset-day":
        if value < 1 or value > 31:
            return "Reset day must be between 1 and 31."
        args.reset_day = value
    save_settings(args.settings.expanduser(), args.budget, args.reset_day)
    return "Saved."


def render_menu_view(
    item: MenuItem,
    summary: Summary,
    periods: Periods,
    budget: int,
    pricing_file: PricingFile,
    workspace_storage: object,
    args: argparse.Namespace,
) -> str:
    """Render the right-hand detail pane for the selected menu item."""

    view = item.view or "summary"
    totals = period_totals(periods, item.period)
    if view == "summary":
        return render_plain_summary(summary, periods, budget, pricing_file)
    if view == "models":
        return captured_output(print_models, totals, f"Models ({item.period})")
    if view == "workspaces":
        return captured_output(print_workspaces, totals, f"Workspaces ({item.period})")
    if view == "unknown":
        return render_unknown(summary)
    if view == "settings":
        return render_settings(args)
    if view == "paths":
        return render_paths(workspace_storage, args.copilot_home.expanduser(), [path.expanduser() for path in args.data_path], pricing_file.path, args.settings.expanduser())
    return ""


def clear_terminal() -> None:
    """Clear the terminal using the platform shell command."""

    os.system("cls" if platform.system() == "Windows" else "clear")


def text_menu_screen(
    items: list[MenuItem],
    selected: int,
    active: MenuItem,
    summary: Summary,
    periods: Periods,
    pricing_file: PricingFile,
    workspace_storage: object,
    interval: int,
    color: bool,
    args: argparse.Namespace,
) -> str:
    """Render the menu as plain text for Windows and tests."""

    width = shutil.get_terminal_size((100, 30)).columns
    nav_width = min(30, max(22, width // 4))
    detail_width = max(30, width - nav_width - 3)
    rows = flatten_menu(items)
    lines: list[str] = []
    lines.extend(colorize(line, CYAN, color) for line in LOGO)
    lines.append(colorize(BYLINE, DIM, color))
    lines.append(colorize("↑↓ move  →/Enter open  ← back  q quit", DIM, color))
    lines.append("")

    content = render_menu_view(active, summary, periods, args.budget, pricing_file, workspace_storage, args).splitlines()
    max_rows = max(len(rows), len(content) + 3)
    for index in range(max_rows):
        if index < len(rows):
            item, depth, _ = rows[index]
            marker = ("▾ " if item.expanded else "▸ ") if item.children else "  "
            pointer = colorize(">", CYAN, color) if index == selected else " "
            menu_text = f"{pointer} {'  ' * depth}{marker}{item.title}"
        else:
            menu_text = ""

        if index == 0:
            title_color = GREEN if periods.usage_balance >= 0 else RED
            detail = colorize(view_title(active), title_color, color)
        elif index == 1:
            detail = colorize(f"Auto-refresh: {interval}s", DIM, color)
        elif index == 2:
            detail = ""
        else:
            detail = content[index - 3] if index - 3 < len(content) else ""
            if active.view == "summary" and detail.startswith("Pace"):
                detail = colorize(detail, GREEN if periods.usage_balance >= 0 else RED, color)
        lines.append(f"{menu_text[:nav_width].ljust(nav_width)} │ {detail[:detail_width]}")
    return "\n".join(lines)


def run_windows_menu(args: argparse.Namespace, snapshot_callback: Any) -> int:
    """Run the keyboard menu with Windows' built-in msvcrt module."""

    import msvcrt

    items = menu_items()
    selected = 0
    active = items[0]
    last_refresh = 0.0
    summary, periods, _, pricing_file = snapshot_callback(args)

    try:
        while True:
            rows = flatten_menu(items)
            selected = max(0, min(selected, len(rows) - 1))
            now = time.monotonic()
            if now - last_refresh >= args.interval:
                summary, periods, _, pricing_file = snapshot_callback(args)
                last_refresh = now

            clear_terminal()
            safe_print(text_menu_screen(items, selected, active, summary, periods, pricing_file, args.workspace_storage.expanduser(), args.interval, False, args))

            deadline = time.monotonic() + min(args.interval, 0.25)
            while time.monotonic() < deadline and not msvcrt.kbhit():
                time.sleep(0.03)
            if not msvcrt.kbhit():
                continue

            key = msvcrt.getwch()
            if key in ("\x00", "\xe0"):
                selected, active = handle_windows_arrow(msvcrt.getwch(), items, selected, rows, active)
                continue

            if key.lower() == "q" or key == "\x1b":
                return 0
            if key == "\r":
                item, _, _ = rows[selected]
                if item.children:
                    item.expanded = True
                elif item.action:
                    active = prompt_windows_setting(args, item.action, snapshot_callback)
                    summary, periods, _, pricing_file = snapshot_callback(args)
                    last_refresh = 0.0
                else:
                    active = item
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


def handle_windows_arrow(key: str, items: list[MenuItem], selected: int, rows: list[tuple[MenuItem, int, MenuItem | None]], active: MenuItem) -> tuple[int, MenuItem]:
    """Apply a Windows arrow-key action to menu selection state."""

    if key == "H":
        selected = max(0, selected - 1)
    elif key == "P":
        selected = min(len(rows) - 1, selected + 1)
    elif key == "M":
        item, _, _ = rows[selected]
        if item.children:
            item.expanded = True
        else:
            active = item
    elif key == "K":
        item, _, parent = rows[selected]
        if item.children and item.expanded:
            item.expanded = False
        elif parent:
            parent.expanded = False
            selected = next((idx for idx, (candidate, _, _) in enumerate(flatten_menu(items)) if candidate is parent), selected)
    return selected, active


def prompt_windows_setting(args: argparse.Namespace, action: str, snapshot_callback: Any) -> MenuItem:
    """Prompt for a setting in the Windows text menu."""

    clear_terminal()
    prompt = "Monthly budget" if action == "set-budget" else "Reset day (1-31)"
    current = args.budget if action == "set-budget" else args.reset_day
    raw_value = input(f"{prompt} [{current}]: ").strip()
    message = set_runtime_setting(args, action, raw_value)
    print(message)
    time.sleep(0.8)
    snapshot_callback(args)
    return next(child for child in menu_items()[4].children if child.view == "settings")


def run_menu(args: argparse.Namespace, snapshot_callback: Any) -> int:
    """Run the curses menu on Unix-like systems or the Windows text menu."""

    if platform.system() == "Windows":
        return run_windows_menu(args, snapshot_callback)

    try:
        import curses
    except ImportError:
        print("Interactive menu is not available on this Python build. Falling back to watch mode.")
        return 1

    items = menu_items()
    selected = 0
    active = items[0]

    def safe_add(window: Any, y: int, x: int, text: str, width: int, attr: int = 0) -> None:
        """Add text to curses, ignoring boundary errors from small terminals."""

        if y < 0 or width <= 0:
            return
        try:
            window.addnstr(y, x, text, width, attr)
        except curses.error:
            pass

    def draw(stdscr: Any) -> None:
        """Draw and update the curses UI until the user quits."""

        nonlocal selected, active
        color_enabled = False
        green_pair = red_pair = cyan_pair = dim_pair = selected_pair = 0
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        try:
            if not args.no_color and curses.has_colors():
                curses.start_color()
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_GREEN, -1)
                curses.init_pair(2, curses.COLOR_RED, -1)
                curses.init_pair(3, curses.COLOR_CYAN, -1)
                curses.init_pair(4, curses.COLOR_WHITE, -1)
                curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)
                green_pair = curses.color_pair(1)
                red_pair = curses.color_pair(2)
                cyan_pair = curses.color_pair(3)
                dim_pair = curses.color_pair(4) | curses.A_DIM
                selected_pair = curses.color_pair(5)
                color_enabled = True
        except curses.error:
            color_enabled = False
        stdscr.timeout(250)
        last_refresh = 0.0
        summary, periods, _, pricing_file = snapshot_callback(args)

        def prompt_setting(action: str) -> None:
            """Prompt for a setting inside curses mode."""

            nonlocal active, summary, periods, pricing_file, last_refresh
            prompt = "Monthly budget" if action == "set-budget" else "Reset day (1-31)"
            current = args.budget if action == "set-budget" else args.reset_day
            height, width = stdscr.getmaxyx()
            try:
                curses.curs_set(1)
            except curses.error:
                pass
            curses.echo()
            stdscr.timeout(-1)
            safe_add(stdscr, height - 2, 0, " " * max(0, width - 1), max(0, width - 1))
            safe_add(stdscr, height - 2, 0, f"{prompt} [{current}]: ", max(0, width - 1), curses.A_BOLD)
            stdscr.refresh()
            try:
                raw = stdscr.getstr(height - 2, len(f"{prompt} [{current}]: "), 20).decode(errors="replace").strip()
            except Exception:
                raw = ""
            curses.noecho()
            stdscr.timeout(250)
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            message = set_runtime_setting(args, action, raw)
            safe_add(stdscr, height - 1, 0, " " * max(0, width - 1), max(0, width - 1))
            safe_add(stdscr, height - 1, 0, message, max(0, width - 1), green_pair if message == "Saved." else red_pair)
            stdscr.refresh()
            time.sleep(0.8)
            active = next(child for child in menu_items()[4].children if child.view == "settings")
            summary, periods, _, pricing_file = snapshot_callback(args)
            last_refresh = 0.0

        while True:
            now = time.monotonic()
            if now - last_refresh >= args.interval:
                summary, periods, _, pricing_file = snapshot_callback(args)
                last_refresh = now

            rows = flatten_menu(items)
            selected = max(0, min(selected, len(rows) - 1))
            height, width = stdscr.getmaxyx()
            nav_width = min(30, max(22, width // 4))
            stdscr.erase()

            for index, line in enumerate(LOGO):
                safe_add(stdscr, index, 1, line, nav_width - 2, curses.A_BOLD | cyan_pair)
            safe_add(stdscr, 3, 1, BYLINE, nav_width - 2, dim_pair if color_enabled else curses.A_DIM)
            safe_add(stdscr, 5, 1, "↑↓ move  →/Enter open  ← back  q quit", width - 2, dim_pair if color_enabled else curses.A_DIM)

            for y in range(height):
                safe_add(stdscr, y, nav_width, "│", 1, curses.A_DIM)

            menu_top = 7
            for row_index, (item, depth, _) in enumerate(rows):
                y = menu_top + row_index
                if y >= height - 2:
                    break
                prefix = "  " * depth
                marker = "▾ " if item.children and item.expanded else "▸ " if item.children else "  "
                attr = selected_pair if row_index == selected and color_enabled else curses.A_REVERSE if row_index == selected else 0
                safe_add(stdscr, y, 1, f"{prefix}{marker}{item.title}", nav_width - 2, attr)

            detail_x = nav_width + 2
            detail_width = width - detail_x - 1
            status_pair = green_pair if periods.usage_balance >= 0 else red_pair
            safe_add(stdscr, 0, detail_x, view_title(active), detail_width, curses.A_BOLD | status_pair)
            safe_add(stdscr, 1, detail_x, f"Auto-refresh: {args.interval}s", detail_width, dim_pair if color_enabled else curses.A_DIM)
            content = render_menu_view(active, summary, periods, args.budget, pricing_file, args.workspace_storage.expanduser(), args)
            for index, line in enumerate(content.splitlines()):
                y = 3 + index
                if y >= height - 2:
                    safe_add(stdscr, height - 2, detail_x, "…", detail_width, curses.A_DIM)
                    break
                line_attr = green_pair if active.view == "summary" and line.startswith("Pace") and periods.usage_balance >= 0 else red_pair if active.view == "summary" and line.startswith("Pace") else 0
                safe_add(stdscr, y, detail_x, line, detail_width, line_attr)

            stdscr.refresh()
            key = stdscr.getch()
            if key == -1:
                continue
            if key in (ord("q"), ord("Q"), 27):
                return
            if key == curses.KEY_UP:
                selected = max(0, selected - 1)
            elif key == curses.KEY_DOWN:
                selected = min(len(rows) - 1, selected + 1)
            elif key in (curses.KEY_RIGHT, ord("\n"), ord("\r")):
                item, _, _ = rows[selected]
                if item.children:
                    item.expanded = True
                elif item.action:
                    prompt_setting(item.action)
                else:
                    active = item
            elif key == curses.KEY_LEFT:
                item, _, parent = rows[selected]
                if item.children and item.expanded:
                    item.expanded = False
                elif parent:
                    parent.expanded = False
                    selected = next((idx for idx, (candidate, _, _) in enumerate(flatten_menu(items)) if candidate is parent), selected)

    try:
        import curses

        curses.wrapper(draw)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0
