"""Shared constants for ModelMeter."""

from __future__ import annotations

import re
from typing import Any

CREDITS_PER_USD = 100
DEFAULT_BUDGET = 2500
DEFAULT_RESET_DAY = 1

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
AMBER = "\033[33m"
CYAN = "\033[36m"

LOGO = (
    "┳┳┓   ┓  ┓  ┳┳┓       ",
    "┃┃┃┏┓┏┫┏┓┃  ┃┃┃┏┓╋┏┓┏┓",
    "┛ ┗┗┛┗┻┗ ┗  ┛ ┗┗ ┗┗ ┛ ",
)
BYLINE = "by TurtleBot · v1.2"

DEFAULT_PRICING: dict[str, Any] = {
    "version": "2026-06-02",
    "creditsPerUsd": CREDITS_PER_USD,
    "models": {
        "gpt-4.1": {"input": 2, "cachedInput": 0.5, "output": 8},
        "gpt-5-mini": {"input": 0.25, "cachedInput": 0.025, "output": 2},
        "gpt-5.2": {"input": 1.75, "cachedInput": 0.175, "output": 14},
        "gpt-5.2-codex": {"input": 1.75, "cachedInput": 0.175, "output": 14},
        "gpt-5.3-codex": {"input": 1.75, "cachedInput": 0.175, "output": 14},
        "gpt-5.4": {"input": 2.5, "cachedInput": 0.25, "output": 15},
        "gpt-5.4-mini": {"input": 0.75, "cachedInput": 0.075, "output": 4.5},
        "gpt-5.4-nano": {"input": 0.2, "cachedInput": 0.02, "output": 1.25},
        "gpt-5.5": {"input": 5, "cachedInput": 0.5, "output": 30},
        "claude-haiku-4.5": {"input": 1, "cachedInput": 0.1, "cacheWrite": 1.25, "output": 5},
        "claude-sonnet-4": {"input": 3, "cachedInput": 0.3, "cacheWrite": 3.75, "output": 15},
        "claude-sonnet-4.5": {"input": 3, "cachedInput": 0.3, "cacheWrite": 3.75, "output": 15},
        "claude-sonnet-4.6": {"input": 3, "cachedInput": 0.3, "cacheWrite": 3.75, "output": 15},
        "claude-opus-4.5": {"input": 5, "cachedInput": 0.5, "cacheWrite": 6.25, "output": 25},
        "claude-opus-4.6": {"input": 5, "cachedInput": 0.5, "cacheWrite": 6.25, "output": 25},
        "claude-opus-4.7": {"input": 5, "cachedInput": 0.5, "cacheWrite": 6.25, "output": 25},
        "gemini-2.5-pro": {"input": 1.25, "cachedInput": 0.125, "output": 10},
        "gemini-3-flash": {"input": 0.5, "cachedInput": 0.05, "output": 3},
        "gemini-3.1-pro": {"input": 2, "cachedInput": 0.2, "output": 12},
        "grok-code-fast-1": {"input": 0.2, "cachedInput": 0.02, "output": 1.5},
        "raptor-mini": {"input": 0.25, "cachedInput": 0.025, "output": 2},
        "goldeneye": {"input": 1.75, "cachedInput": 0.175, "output": 14},
    },
}
