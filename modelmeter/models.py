"""Typed data structures used across ModelMeter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Pricing:
    """Per-million-token prices for a model."""

    input: float
    cached_input: float
    output: float
    cache_write: float | None = None


@dataclass(frozen=True)
class PricingFile:
    """Parsed pricing configuration and any read error encountered."""

    path: Path
    version: str
    models: dict[str, Pricing]
    error: str | None = None


@dataclass(frozen=True)
class PricingMatch:
    """Result of matching a usage record's model name to pricing."""

    source: str
    pricing: Pricing | None = None
    matched_model: str | None = None


@dataclass(frozen=True)
class SessionFile:
    """A Copilot Chat session file with workspace context."""

    path: Path
    workspace_id: str
    workspace_name: str


@dataclass(frozen=True)
class RequestUsage:
    """Usage attributed to one model response."""

    response_id: str
    model: str
    workspace: str
    timestamp: datetime
    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    output_tokens: int
    recorded_credits: float | None
    estimated_credits: float | None
    pricing_match: PricingMatch
    source: str = "unknown"

    @property
    def credits(self) -> float:
        """Return recorded credits when present, otherwise the estimate."""

        return self.recorded_credits if self.recorded_credits is not None else (self.estimated_credits or 0.0)

    @property
    def total_tokens(self) -> int:
        """Return all billable and cached token buckets combined."""

        return self.input_tokens + self.cached_input_tokens + self.cache_write_tokens + self.output_tokens

    @property
    def dedupe_key(self) -> str:
        """Return a stable key used to prevent cross-source double counting."""

        if self.response_id:
            return f"response:{self.response_id}"
        credit = self.recorded_credits if self.recorded_credits is not None else self.estimated_credits
        return (
            "usage:"
            f"{self.timestamp.isoformat()}:{self.workspace}:{self.model}:"
            f"{self.input_tokens}:{self.cached_input_tokens}:{self.cache_write_tokens}:"
            f"{self.output_tokens}:{credit}"
        )


@dataclass
class Totals:
    """Aggregated usage counters for a period, model, or workspace."""

    requests: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    displayed_credits: float = 0.0
    recorded_credits: float = 0.0
    estimated_credits: float = 0.0
    requests_with_recorded_credits: int = 0
    requests_with_estimated_credits: int = 0
    requests_with_fallback_pricing: int = 0
    requests_with_unknown_pricing: int = 0
    unknown_models: set[str] = field(default_factory=set)
    models: dict[str, "Totals"] = field(default_factory=dict)
    workspaces: dict[str, "Totals"] = field(default_factory=dict)
    daily_credits: dict[str, float] = field(default_factory=dict)

    @property
    def credits(self) -> float:
        """Return the user-facing credits total."""

        return self.displayed_credits

    @property
    def total_tokens(self) -> int:
        """Return all token buckets combined."""

        return self.input_tokens + self.cached_input_tokens + self.cache_write_tokens + self.output_tokens

    def add(self, request: RequestUsage) -> None:
        """Add a request to this aggregate."""

        self.requests += 1
        self.input_tokens += request.input_tokens
        self.cached_input_tokens += request.cached_input_tokens
        self.cache_write_tokens += request.cache_write_tokens
        self.output_tokens += request.output_tokens
        self.displayed_credits += request.credits
        self.recorded_credits += request.recorded_credits or 0
        self.estimated_credits += request.estimated_credits or 0
        if request.recorded_credits is not None:
            self.requests_with_recorded_credits += 1
        if request.estimated_credits is not None:
            self.requests_with_estimated_credits += 1
        if request.pricing_match.source == "fallback":
            self.requests_with_fallback_pricing += 1
        if request.pricing_match.source == "unknown":
            self.requests_with_unknown_pricing += 1
            self.unknown_models.add(request.model)


@dataclass
class Summary(Totals):
    """Full scan summary across all discovered session files."""

    files: int = 0
    sessions_with_usage: int = 0
    requests_list: list[RequestUsage] = field(default_factory=list)


@dataclass(frozen=True)
class Periods:
    """Current, previous, and all-time aggregates plus pacing metrics."""

    current: Totals
    previous: Totals
    all_time: Totals
    current_start: datetime
    current_end: datetime
    previous_start: datetime
    expected_credits: float
    usage_balance: float
    burn_rate_per_day: float
    projected_credits: float
    days_remaining: int
