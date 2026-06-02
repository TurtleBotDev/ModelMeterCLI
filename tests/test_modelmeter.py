"""Regression tests for the ModelMeter core."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from modelmeter.models import Pricing, PricingFile, RequestUsage, Summary
from modelmeter.periods import build_periods, period_start_for
from modelmeter.pricing import canonical_model_name, estimate_credits, resolve_pricing
from modelmeter.sessions import collect_session_usage, find_chat_session_files


class PricingTests(unittest.TestCase):
    """Tests for model normalization and pricing estimates."""

    def setUp(self) -> None:
        """Create a small pricing file fixture."""

        self.pricing_file = PricingFile(
            path=Path("pricing.json"),
            version="test",
            models={
                "gpt-5-mini": Pricing(input=1.0, cached_input=0.1, cache_write=1.25, output=4.0),
                "claude-sonnet-4": Pricing(input=3.0, cached_input=0.3, cache_write=3.75, output=15.0),
            },
        )

    def test_canonical_model_name_removes_copilot_and_date_suffixes(self) -> None:
        """Dated Copilot model names normalize to configured pricing keys."""

        self.assertEqual(canonical_model_name("Copilot GPT 5 Mini-2026-01-31"), "gpt-5-mini")

    def test_resolve_pricing_uses_family_fallback(self) -> None:
        """New provider-family aliases fall back to configured family pricing."""

        match = resolve_pricing("claude-sonnet-4.9", self.pricing_file)
        self.assertEqual(match.source, "fallback")
        self.assertEqual(match.matched_model, "claude-sonnet-4")

    def test_estimate_credits_uses_all_token_buckets(self) -> None:
        """Credit estimates include input, cached input, cache write, and output."""

        credits, match = estimate_credits(
            {
                "model": "gpt-5-mini",
                "input_tokens": 1_000_000,
                "cached_input_tokens": 1_000_000,
                "cache_write_tokens": 1_000_000,
                "output_tokens": 1_000_000,
            },
            self.pricing_file,
        )
        self.assertEqual(match.source, "exact")
        self.assertAlmostEqual(credits, 635.0)


class PeriodTests(unittest.TestCase):
    """Tests for reset-period calculations."""

    def test_period_start_clamps_reset_day_for_short_month(self) -> None:
        """A 31st reset day maps to February 28 in non-leap years."""

        value = datetime(2026, 2, 28, 12, tzinfo=timezone.utc)
        self.assertEqual(period_start_for(value, 31), datetime(2026, 2, 28, tzinfo=timezone.utc))

    def test_build_periods_uses_supplied_now_for_determinism(self) -> None:
        """Period metrics can be calculated deterministically in tests."""

        summary = Summary()
        summary.requests_list.append(
            RequestUsage(
                response_id="r1",
                model="gpt",
                workspace="repo",
                timestamp=datetime(2026, 6, 2, tzinfo=timezone.utc),
                input_tokens=1,
                cached_input_tokens=0,
                cache_write_tokens=0,
                output_tokens=1,
                recorded_credits=10.0,
                estimated_credits=None,
                pricing_match=resolve_pricing("unknown", PricingFile(Path("p"), "v", {})),
            )
        )
        periods = build_periods(summary, 300, 1, now=datetime(2026, 6, 16, tzinfo=timezone.utc))
        self.assertEqual(periods.current.requests, 1)
        self.assertGreater(periods.expected_credits, 0)


class SessionTests(unittest.TestCase):
    """Tests for session discovery and parsing."""

    def test_find_and_parse_chat_session_files(self) -> None:
        """Workspace storage discovery and usage parsing work with JSONL sessions."""

        with tempfile.TemporaryDirectory() as tmp:
            storage = Path(tmp)
            workspace = storage / "abc"
            chat = workspace / "chatSessions"
            chat.mkdir(parents=True)
            (workspace / "workspace.json").write_text(json.dumps({"folder": "file:///Users/me/Project"}), encoding="utf-8")
            session = chat / "one.jsonl"
            session.write_text(
                json.dumps(
                    {
                        "responseId": "r1",
                        "resolvedModel": "gpt-5-mini",
                        "timestamp": 1_780_000_000_000,
                        "usage": {
                            "promptTokens": 1000,
                            "completionTokens": 200,
                            "promptTokenDetails": [{"category": "System", "percentageOfPrompt": 50}],
                        },
                        "details": "gpt-5-mini • 3.5 credits",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            files = find_chat_session_files(storage)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].workspace_name, "Project")

            pricing_file = PricingFile(Path("pricing.json"), "test", {"gpt-5-mini": Pricing(1, 0.1, 4, 1.25)})
            requests = collect_session_usage(files[0], pricing_file)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].cache_write_tokens, 500)
            self.assertEqual(requests[0].recorded_credits, 3.5)


if __name__ == "__main__":
    unittest.main()
