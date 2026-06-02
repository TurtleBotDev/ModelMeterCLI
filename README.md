# ModelMeterCLI

ModelMeterCLI is a zero-dependency Python command-line tool for tracking local GitHub Copilot usage across local editor and CLI data sources.

It scans Copilot usage files already stored on your machine, reads or estimates AI credit usage, and shows whether your current monthly reset period is under or over pace for your budget.

No extension. No API token. No `pip install`. Just Python's standard library.

## Why Use It

Copilot Chat usage can be hard to reason about across projects, models, and reset periods. ModelMeterCLI gives you a local dashboard for:

- Current-period AI credit usage
- Under/over pace status for a monthly budget
- Projected end-of-period usage
- Model and workspace breakdowns
- Unknown model detection with pricing snippets
- JSON output for scripts and automations
- Source-level de-duplication so overlapping logs do not double-count usage

All data stays local. ModelMeterCLI does not call GitHub APIs, does not ask for credentials, and does not upload your session files.

## Quick Start

Download the latest `modelmeter.pyz` from the GitHub releases page, then run:

```sh
python3 modelmeter.pyz
```

The `.pyz` file is built with Python's standard-library `zipapp` module. It is a single-file runnable archive, but it still requires Python 3.10 or newer on your machine.

## Source Checkout

Clone the repo and run:

```sh
python3 modelmeter.py
```

Or run it as a Python module:

```sh
python3 -m modelmeter
```

By default, ModelMeterCLI opens an interactive terminal menu and refreshes every 30 seconds.

Use the arrow keys to move, `Enter` or right arrow to open/select, left arrow to collapse, and `q` to quit.

## Requirements

- Python 3.10 or newer
- Local Copilot usage files from VS Code and/or Copilot CLI
- No third-party Python packages

On macOS and Linux, the interactive menu uses Python's built-in `curses` module. On Windows, it uses Python's built-in `msvcrt` module. Windows Terminal is recommended for the cleanest rendering.

If an older Windows shell has trouble with box drawing characters, enable UTF-8 first:

```bat
chcp 65001
python modelmeter.py
```

## Commands

```sh
python3 modelmeter.py menu
python3 modelmeter.py watch
python3 modelmeter.py summary
python3 modelmeter.py models --period current
python3 modelmeter.py models --period previous
python3 modelmeter.py models --period all
python3 modelmeter.py workspaces --period all
python3 modelmeter.py unknown
python3 modelmeter.py json
python3 modelmeter.py paths
python3 modelmeter.py init-pricing
```

The passive dashboard is useful when you want a simple refreshing view:

```sh
python3 modelmeter.py watch
python3 modelmeter.py watch --interval 60 --no-clear
```

Disable terminal color when needed:

```sh
python3 modelmeter.py --no-color
```

## Budget And Reset Day

Set a monthly AI credit budget and reset day:

```sh
python3 modelmeter.py --budget 2500 --reset-day 1
```

You can also save these values from the interactive menu:

```text
Settings > Set Budget
Settings > Set Reset Day
```

Saved settings live at:

```text
~/.copilot/modelmeter-settings.json
```

Command-line flags override saved settings for that run.

## Data Sources

By default, ModelMeterCLI scans three local source families:

```text
VS Code chatSessions       <VS Code User>/workspaceStorage/<workspace>/chatSessions/
VS Code debug logs         <VS Code User>/{globalStorage,workspaceStorage}/.../debug-logs/
Copilot CLI session data   ~/.copilot/session-state/*/events.jsonl
```

VS Code debug logs are the most accurate local source when they include GitHub's recorded AI credit field:

```text
copilotUsageNanoAiu
```

To make VS Code write Copilot agent debug events to disk, enable this VS Code setting:

```text
github.copilot.chat.agentDebugLog.fileLogging.enabled
```

Copilot CLI data is read from `COPILOT_HOME` when set, otherwise:

```text
~/.copilot
```

You can override the detected locations:

```sh
python3 modelmeter.py --workspace-storage "/path/to/workspaceStorage"
python3 modelmeter.py --copilot-home "/path/to/.copilot"
python3 modelmeter.py --data-path "/extra/local/usage/folder"
```

ModelMeterCLI de-duplicates requests across sources by response/session identifiers when present, and by a conservative usage fingerprint otherwise. This is important because the same Copilot request can appear in both a chat session file and a debug log.

Useful path discovery:

```sh
python3 modelmeter.py paths
```

## Current Coverage

- VS Code / VS Code Insiders: chat session files and Copilot debug log JSON/JSONL files.
- Copilot CLI: local `session-state` JSONL events that expose token or AI credit fields.
- Visual Studio, JetBrains/Rider, Xcode: researched but not yet counted unless their logs contain compatible JSON/JSONL usage records and are passed with `--data-path`.

The tool stays intentionally local-first. An authenticated GitHub metrics/API mode would be a separate future feature.

## Pricing

Pricing lives in:

```text
~/.copilot/modelmeter-pricing.json
```

ModelMeterCLI creates this file automatically if it does not exist.

When it finds a model that is not in the pricing file, print ready-to-edit JSON snippets with:

```sh
python3 modelmeter.py unknown
```

Pricing is intentionally local and editable because model names and prices can change over time.

## JSON Output

For scripts, dashboards, or reporting pipelines:

```sh
python3 modelmeter.py json
```

The JSON output includes budget settings, current-period pacing metrics, previous-period usage, all-time scanned usage, model breakdowns, workspace breakdowns, and daily credit totals.

## Project Structure

```text
modelmeter.py              launcher for `python3 modelmeter.py`
modelmeter/__main__.py     launcher for `python3 -m modelmeter`
modelmeter/cli.py          argument parsing and command dispatch
modelmeter/config.py       platform paths and saved settings
modelmeter/pricing.py      pricing file parsing and model matching
modelmeter/sessions.py     VS Code Copilot session discovery and parsing
modelmeter/sources.py      VS Code debug-log and Copilot CLI source adapters
modelmeter/periods.py      reset-period and pacing calculations
modelmeter/render.py       terminal, table, and JSON rendering
modelmeter/menu.py         interactive terminal menu
modelmeter/models.py       typed data structures
tests/test_modelmeter.py   stdlib unittest coverage for core behavior
```

## Development

Run the test suite:

```sh
python3 -m unittest discover -s tests
```

Run a quick syntax check:

```sh
python3 -m py_compile modelmeter.py modelmeter/*.py tests/*.py
```

Build the single-file release artifact:

```sh
python3 tools/build_zipapp.py
python3 dist/modelmeter.pyz
```

ModelMeterCLI is deliberately standard-library-only. Please avoid adding runtime dependencies unless the project direction explicitly changes.

## Privacy

ModelMeterCLI reads local Copilot session/log files and local configuration files. It does not:

- Send usage data to GitHub
- Send usage data to OpenAI
- Require a GitHub token
- Require an API key
- Install a VS Code extension

If you publish logs, screenshots, or JSON output, review them first for workspace names or model usage details you consider private.

## License

MIT License. See [LICENSE](LICENSE).
