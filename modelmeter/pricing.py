"""Pricing file parsing and model-to-price matching."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .constants import CREDITS_PER_USD, DEFAULT_PRICING
from .models import Pricing, PricingFile, PricingMatch


def ensure_pricing_file(path: Path) -> None:
    """Create the default pricing file when it does not already exist."""

    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DEFAULT_PRICING, indent=2) + "\n", encoding="utf-8")


def canonical_model_name(model: str) -> str:
    """Normalize model names so dated aliases can match configured pricing."""

    value = model.lower()
    value = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", value)
    value = re.sub(r"-\d{8}$", "", value)
    value = re.sub(r"^copilot[-\s]*", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def read_number(value: Any) -> float:
    """Return a finite numeric value, or zero for anything else."""

    return value if isinstance(value, (int, float)) and math.isfinite(value) else 0.0


def read_pricing_file(path: Path) -> PricingFile:
    """Read model pricing from disk, creating the default file if needed."""

    ensure_pricing_file(path)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return PricingFile(path=path, version="unknown", models={}, error=str(exc))

    models: dict[str, Pricing] = {}
    for model, entry in parsed.get("models", {}).items():
        if not isinstance(entry, dict):
            continue
        input_price = read_number(entry.get("input"))
        cached_input = read_number(entry.get("cachedInput"))
        output = read_number(entry.get("output"))
        cache_write = read_number(entry.get("cacheWrite"))
        if input_price <= 0 or cached_input < 0 or output <= 0:
            continue
        models[canonical_model_name(str(model))] = Pricing(
            input=input_price,
            cached_input=cached_input,
            output=output,
            cache_write=cache_write if cache_write > 0 else None,
        )

    return PricingFile(path=path, version=str(parsed.get("version", "unknown")), models=models)


def resolve_pricing(model: str, pricing_file: PricingFile) -> PricingMatch:
    """Find exact pricing, then provider-family fallback pricing, for a model."""

    canonical = canonical_model_name(model)
    exact = pricing_file.models.get(canonical)
    if exact:
        return PricingMatch(source="exact", pricing=exact)

    families = ("opus", "sonnet", "haiku", "gemini", "gpt")
    for family in families:
        if family not in canonical:
            continue
        for candidate, pricing in pricing_file.models.items():
            if family in candidate:
                return PricingMatch(source="fallback", pricing=pricing, matched_model=candidate)
    return PricingMatch(source="unknown")


def estimate_credits(request: dict[str, Any], pricing_file: PricingFile) -> tuple[float | None, PricingMatch]:
    """Estimate AI credits for token usage using the configured pricing file."""

    match = resolve_pricing(str(request["model"]), pricing_file)
    pricing = match.pricing
    if not pricing:
        return None, match

    usd = (
        request["input_tokens"] / 1_000_000 * pricing.input
        + request["cached_input_tokens"] / 1_000_000 * pricing.cached_input
        + request["cache_write_tokens"] / 1_000_000 * (pricing.cache_write if pricing.cache_write is not None else pricing.input)
        + request["output_tokens"] / 1_000_000 * pricing.output
    )
    return usd * CREDITS_PER_USD, match
