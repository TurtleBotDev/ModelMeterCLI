# ModelMeter

ModelMeter is a stdlib-only Python CLI for local Copilot Chat usage pacing.

It scans local VS Code Copilot Chat session files, estimates or reads AI credit usage, and reports whether your current reset period is under or over pace for a monthly AI credit budget.

No extension install is required. No `pip install` is required.

## Project Shape

ModelMeter keeps the executable entry point small and puts the implementation in a focused package:

```text
modelmeter.py              launcher for `python3 modelmeter.py`
modelmeter/cli.py          argument parsing and command dispatch
modelmeter/config.py       platform paths and saved settings
modelmeter/pricing.py      pricing file parsing and model matching
modelmeter/sessions.py     VS Code Copilot session discovery and parsing
modelmeter/periods.py      reset-period and pacing calculations
modelmeter/render.py       terminal, table, and JSON rendering
modelmeter/menu.py         interactive terminal menu
tests/test_modelmeter.py   stdlib unittest coverage for core behavior
```

## Run

```sh
python3 modelmeter.py
```

You can also run the package module directly:

```sh
python3 -m modelmeter
```

By default, ModelMeter opens an interactive terminal menu and refreshes every 30 seconds.

Use arrow keys to move, `Enter` or right arrow to open/select, left arrow to collapse, and `q` to quit.

On macOS/Linux the menu uses Python's built-in `curses`. On Windows it uses Python's built-in `msvcrt`, so no package install is needed there either. Windows Terminal should render the box/logo best; older `cmd.exe` may need UTF-8 enabled:

```bat
chcp 65001
python modelmeter.py
```

ModelMeter uses terminal colours for under/over pace when supported. Disable them with:

```sh
python3 modelmeter.py --no-color
```

```sh
python3 modelmeter.py --interval 30
python3 modelmeter.py menu --interval 30
```

For the simpler passive dashboard:

```sh
python3 modelmeter.py watch
python3 modelmeter.py watch --interval 30 --no-clear
```

Useful commands:

```sh
python3 modelmeter.py watch
python3 modelmeter.py menu
python3 modelmeter.py summary
python3 modelmeter.py models --period current
python3 modelmeter.py models --period previous
python3 modelmeter.py models --period all
python3 modelmeter.py workspaces --period all
python3 modelmeter.py unknown
python3 modelmeter.py json
python3 modelmeter.py paths
```

Budget/reset options:

```sh
python3 modelmeter.py --budget 2500 --reset-day 1
```

You can also change these from the interactive menu:

```text
Settings > Set Budget
Settings > Set Reset Day
```

Saved settings live in:

```text
~/.copilot/modelmeter-settings.json
```

## Data Source

By default, ModelMeter scans:

```text
<VS Code User>/workspaceStorage/<workspace>/chatSessions/
```

You can point it somewhere else:

```sh
python3 modelmeter.py --workspace-storage "/path/to/workspaceStorage"
```

It does not ask for a GitHub token and does not call GitHub APIs.

## Pricing

Pricing lives in:

```text
~/.copilot/modelmeter-pricing.json
```

ModelMeter creates this file if it does not exist.

To print unknown model JSON snippets:

```sh
python3 modelmeter.py unknown
```

## Test

ModelMeter uses only Python's built-in `unittest` framework:

```sh
python3 -m unittest discover -s tests
```

For a quick syntax check:

```sh
python3 -m py_compile modelmeter.py modelmeter/*.py tests/*.py
```
