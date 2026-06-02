"""Regression tests for the ModelMeter core."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from modelmeter.models import Pricing, PricingFile, RequestUsage, Summary
from modelmeter.periods import build_periods, period_start_for
from modelmeter.pricing import canonical_model_name, ensure_pricing_file, estimate_credits, read_number, read_pricing_file, resolve_pricing
from modelmeter.sessions import collect_session_usage, find_chat_session_files, summarize_requests
from modelmeter.sources import collect_copilot_cli_usage, collect_vscode_debug_usage


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
        self.assertEqual(canonical_model_name("copilot/gpt-5-mini-20260131"), "gpt-5-mini")

    def test_read_number_rejects_non_finite_and_non_numeric_values(self) -> None:
        """Only finite int and float values should be accepted as prices."""

        self.assertEqual(read_number(2), 2)
        self.assertEqual(read_number(2.5), 2.5)
        self.assertEqual(read_number("2.5"), 0.0)
        self.assertEqual(read_number(float("inf")), 0.0)
        self.assertEqual(read_number(float("nan")), 0.0)

    def test_ensure_pricing_file_creates_default_json(self) -> None:
        """Missing pricing files are created with default model entries."""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "pricing.json"
            ensure_pricing_file(path)

            parsed = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("version", parsed)
            self.assertIn("models", parsed)
            self.assertIn("gpt-5-mini", parsed["models"])

    def test_read_pricing_file_canonicalizes_models_and_skips_invalid_entries(self) -> None:
        """Pricing parsing keeps valid models and ignores incomplete prices."""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pricing.json"
            path.write_text(
                json.dumps(
                    {
                        "version": "fixture",
                        "models": {
                            "Copilot GPT 5 Mini-2026-01-31": {"input": 1, "cachedInput": 0.1, "output": 4},
                            "missing-output": {"input": 1, "cachedInput": 0.1},
                            "negative-input": {"input": -1, "cachedInput": 0.1, "output": 4},
                            "not-an-object": 12,
                        },
                    }
                ),
                encoding="utf-8",
            )

            pricing_file = read_pricing_file(path)
            self.assertEqual(pricing_file.version, "fixture")
            self.assertIsNone(pricing_file.error)
            self.assertEqual(set(pricing_file.models), {"gpt-5-mini"})
            self.assertEqual(pricing_file.models["gpt-5-mini"].output, 4)

    def test_read_pricing_file_reports_malformed_json(self) -> None:
        """Malformed pricing JSON should return an error instead of raising."""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pricing.json"
            path.write_text("{", encoding="utf-8")

            pricing_file = read_pricing_file(path)
            self.assertEqual(pricing_file.version, "unknown")
            self.assertEqual(pricing_file.models, {})
            self.assertIsNotNone(pricing_file.error)

    def test_resolve_pricing_uses_family_fallback(self) -> None:
        """New provider-family aliases fall back to configured family pricing."""

        match = resolve_pricing("claude-sonnet-4.9", self.pricing_file)
        self.assertEqual(match.source, "fallback")
        self.assertEqual(match.matched_model, "claude-sonnet-4")

    def test_resolve_pricing_marks_unknown_models(self) -> None:
        """Models without exact or family pricing should be marked unknown."""

        match = resolve_pricing("mystery-model", self.pricing_file)
        self.assertEqual(match.source, "unknown")
        self.assertIsNone(match.pricing)

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

    def test_estimate_credits_uses_input_price_when_cache_write_price_is_missing(self) -> None:
        """Cache writes should fall back to input pricing when no write price exists."""

        pricing_file = PricingFile(
            path=Path("pricing.json"),
            version="test",
            models={"gpt-plain": Pricing(input=2.0, cached_input=0.2, output=5.0)},
        )
        credits, match = estimate_credits(
            {
                "model": "gpt-plain",
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "cache_write_tokens": 1_000_000,
                "output_tokens": 0,
            },
            pricing_file,
        )

        self.assertEqual(match.source, "exact")
        self.assertAlmostEqual(credits, 200.0)

    def test_estimate_credits_returns_none_for_unknown_model(self) -> None:
        """Unknown models should not produce pretend credit estimates."""

        credits, match = estimate_credits(
            {
                "model": "mystery-model",
                "input_tokens": 1_000_000,
                "cached_input_tokens": 0,
                "cache_write_tokens": 0,
                "output_tokens": 0,
            },
            self.pricing_file,
        )

        self.assertIsNone(credits)
        self.assertEqual(match.source, "unknown")


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

    def test_summarize_requests_deduplicates_overlapping_sources(self) -> None:
        """The same response ID from two sources should only be counted once."""

        timestamp = datetime(2026, 6, 2, tzinfo=timezone.utc)
        match = resolve_pricing("gpt-5-mini", PricingFile(Path("p"), "v", {"gpt-5-mini": Pricing(1, 0.1, 4)}))
        chat_request = RequestUsage(
            response_id="same-response",
            model="gpt-5-mini",
            workspace="repo",
            timestamp=timestamp,
            input_tokens=100,
            cached_input_tokens=0,
            cache_write_tokens=0,
            output_tokens=50,
            recorded_credits=None,
            estimated_credits=1.0,
            pricing_match=match,
            source="vscode-chat-session",
        )
        debug_request = RequestUsage(
            response_id="same-response",
            model="gpt-5-mini",
            workspace="repo",
            timestamp=timestamp,
            input_tokens=100,
            cached_input_tokens=0,
            cache_write_tokens=0,
            output_tokens=50,
            recorded_credits=2.0,
            estimated_credits=1.0,
            pricing_match=match,
            source="vscode-debug-log",
        )

        summary = summarize_requests([chat_request, debug_request], files=2, sessions_with_usage=1)
        self.assertEqual(summary.requests, 1)
        self.assertEqual(summary.credits, 2.0)
        self.assertEqual(summary.requests_list[0].source, "vscode-debug-log")

    def test_collect_vscode_debug_usage_reads_credit_bearing_records(self) -> None:
        """VS Code debug logs with copilotUsageNanoAiu become recorded usage."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Code" / "User"
            storage = root / "workspaceStorage"
            log_dir = root / "globalStorage" / "github.copilot-chat" / "debug-logs"
            log_dir.mkdir(parents=True)
            log_file = log_dir / "requests.jsonl"
            log_file.write_text(
                json.dumps(
                    {
                        "type": "llm_request",
                        "timestamp": "2026-06-02T00:00:00Z",
                        "attrs": {
                            "responseId": "debug-r1",
                            "model": "gpt-5-mini",
                            "inputTokens": 1000,
                            "cachedTokens": 100,
                            "cacheWriteInputTokens": 25,
                            "outputTokens": 200,
                            "copilotUsageNanoAiu": 1_500_000_000,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            pricing_file = PricingFile(Path("pricing.json"), "test", {"gpt-5-mini": Pricing(1, 0.1, 4, 1.25)})

            requests, files = collect_vscode_debug_usage(storage, [], pricing_file)
            request = next(item for item in requests if item.response_id == "debug-r1")
            self.assertGreaterEqual(files, 1)
            self.assertEqual(request.input_tokens, 900)
            self.assertEqual(request.cached_input_tokens, 100)
            self.assertEqual(request.cache_write_tokens, 25)
            self.assertEqual(request.recorded_credits, 1.5)
            self.assertEqual(request.source, "vscode-debug-log")

    def test_collect_copilot_cli_usage_reads_session_state_events(self) -> None:
        """Copilot CLI events with token fields are parsed as CLI usage."""

        with tempfile.TemporaryDirectory() as tmp:
            copilot_home = Path(tmp) / ".copilot"
            session_dir = copilot_home / "session-state" / "cli-session"
            session_dir.mkdir(parents=True)
            events = session_dir / "events.jsonl"
            events.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-06-02T00:00:00Z",
                        "responseId": "cli-r1",
                        "model": "claude-sonnet-4",
                        "input_tokens": 2000,
                        "cached_tokens": 500,
                        "cache_creation_input_tokens": 100,
                        "output_tokens": 300,
                        "copilotUsageNanoAiu": 2_250_000_000,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            pricing_file = PricingFile(Path("pricing.json"), "test", {"claude-sonnet-4": Pricing(3, 0.3, 15, 3.75)})

            requests, files = collect_copilot_cli_usage(copilot_home, pricing_file)
            request = next(item for item in requests if item.response_id == "cli-r1")
            self.assertEqual(files, 1)
            self.assertEqual(request.input_tokens, 1500)
            self.assertEqual(request.cached_input_tokens, 500)
            self.assertEqual(request.cache_write_tokens, 100)
            self.assertEqual(request.recorded_credits, 2.25)
            self.assertEqual(request.source, "copilot-cli")


if __name__ == "__main__":
    unittest.main()
