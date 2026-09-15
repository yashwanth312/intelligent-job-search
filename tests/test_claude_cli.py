"""Tests for the --output-format json envelope parsing in generation/claude_cli.py.
The subprocess call itself is not unit-tested here — only the pure parsing logic,
plus the cmd/env construction in run_claude (Popen itself is mocked)."""
import json
from unittest.mock import MagicMock, patch

import pytest

import generation.claude_cli as claude_cli
from generation.claude_cli import _parse_envelope, run_claude


@pytest.fixture(autouse=True)
def _isolate_usage_db(tmp_path, monkeypatch):
    """run_claude() logs usage via a module-level DB_FILE pointing at the real
    jobs.db. Without this, every mocked run_claude() call below (they return a
    real envelope with a "usage" key, so _log_usage fires for real) wrote a
    row into the production database — 170+ accumulated this way with
    model="m" before this fixture existed. Point it at a throwaway DB instead."""
    monkeypatch.setattr(claude_cli, "DB_FILE", str(tmp_path / "test_usage.db"))


class TestParseEnvelope:
    def test_success_envelope_returns_result_and_usage(self):
        raw = json.dumps({
            "result": '{"verdict": "APPLY"}',
            "is_error": False,
            "usage": {
                "input_tokens": 1200, "output_tokens": 300,
                "cache_creation_input_tokens": 50, "cache_read_input_tokens": 900,
            },
            "total_cost_usd": 0.0123,
            "duration_ms": 4567,
            "num_turns": 1,
        })
        text, usage = _parse_envelope(raw)
        assert text == '{"verdict": "APPLY"}'
        assert usage["input_tokens"] == 1200
        assert usage["output_tokens"] == 300
        assert usage["cache_creation_input_tokens"] == 50
        assert usage["cache_read_input_tokens"] == 900
        assert usage["cost_usd"] == 0.0123
        assert usage["duration_ms"] == 4567
        assert usage["num_turns"] == 1

    def test_is_error_envelope_returns_none_text_but_usage(self):
        raw = json.dumps({
            "result": "",
            "is_error": True,
            "usage": {"input_tokens": 500, "output_tokens": 0},
            "total_cost_usd": 0.001,
        })
        text, usage = _parse_envelope(raw)
        assert text is None
        assert usage["input_tokens"] == 500

    def test_missing_usage_defaults_to_zero(self):
        raw = json.dumps({"result": "hello", "is_error": False})
        text, usage = _parse_envelope(raw)
        assert text == "hello"
        assert usage["input_tokens"] == 0
        assert usage["output_tokens"] == 0
        assert usage["cost_usd"] is None

    def test_legacy_cost_usd_field_used_as_fallback(self):
        raw = json.dumps({"result": "hi", "is_error": False, "cost_usd": 0.02})
        _text, usage = _parse_envelope(raw)
        assert usage["cost_usd"] == 0.02

    def test_malformed_json_falls_back_to_raw_text_no_usage(self):
        raw = "Here is the JSON you asked for: {not actually json"
        text, usage = _parse_envelope(raw)
        assert text == raw
        assert usage is None

    def test_non_dict_json_falls_back_to_raw_text_no_usage(self):
        raw = json.dumps([1, 2, 3])
        text, usage = _parse_envelope(raw)
        assert text == raw
        assert usage is None


def _mock_popen(envelope: dict):
    proc = MagicMock()
    proc.communicate.return_value = (json.dumps(envelope), "")
    proc.returncode = 0
    return proc


class TestRunClaudeCliConstruction:
    """run_claude's subprocess.Popen call is mocked; these assert the cmd/env
    it builds, not real CLI behavior."""

    def test_uses_tools_empty_string_not_disallowed_tools(self):
        with patch("generation.claude_cli.subprocess.Popen") as mock_popen:
            mock_popen.return_value = _mock_popen({"result": "ok", "is_error": False})
            run_claude("hi", model="m", timeout=5)

        cmd = mock_popen.call_args.args[0]
        assert "--tools" in cmd
        assert cmd[cmd.index("--tools") + 1] == ""
        assert "--disallowedTools" not in cmd

    def test_disable_thinking_sets_max_thinking_tokens_env(self):
        with patch("generation.claude_cli.subprocess.Popen") as mock_popen:
            mock_popen.return_value = _mock_popen({"result": "ok", "is_error": False})
            run_claude("hi", model="m", timeout=5, disable_thinking=True)

        env = mock_popen.call_args.kwargs["env"]
        assert env["MAX_THINKING_TOKENS"] == "0"

    def test_no_disable_thinking_leaves_env_untouched(self):
        with patch("generation.claude_cli.subprocess.Popen") as mock_popen:
            mock_popen.return_value = _mock_popen({"result": "ok", "is_error": False})
            run_claude("hi", model="m", timeout=5)

        env = mock_popen.call_args.kwargs["env"]
        assert "MAX_THINKING_TOKENS" not in env

    def test_thinking_budget_tokens_sets_max_thinking_tokens_env(self):
        with patch("generation.claude_cli.subprocess.Popen") as mock_popen:
            mock_popen.return_value = _mock_popen({"result": "ok", "is_error": False})
            run_claude("hi", model="m", timeout=5, thinking_budget_tokens=12_000)

        env = mock_popen.call_args.kwargs["env"]
        assert env["MAX_THINKING_TOKENS"] == "12000"

    def test_disable_thinking_overrides_thinking_budget_tokens(self):
        """disable_thinking=True must win over a budget — 0 means off, not capped."""
        with patch("generation.claude_cli.subprocess.Popen") as mock_popen:
            mock_popen.return_value = _mock_popen({"result": "ok", "is_error": False})
            run_claude("hi", model="m", timeout=5, disable_thinking=True, thinking_budget_tokens=12_000)

        env = mock_popen.call_args.kwargs["env"]
        assert env["MAX_THINKING_TOKENS"] == "0"

    def test_system_prompt_adds_system_prompt_file_flag(self):
        with patch("generation.claude_cli.subprocess.Popen") as mock_popen:
            mock_popen.return_value = _mock_popen({"result": "ok", "is_error": False})
            run_claude("hi", model="m", timeout=5, system_prompt="static instructions")

        cmd = mock_popen.call_args.args[0]
        assert "--system-prompt-file" in cmd
        sys_path = cmd[cmd.index("--system-prompt-file") + 1]
        assert sys_path  # a real temp path was supplied

    def test_no_system_prompt_omits_flag(self):
        with patch("generation.claude_cli.subprocess.Popen") as mock_popen:
            mock_popen.return_value = _mock_popen({"result": "ok", "is_error": False})
            run_claude("hi", model="m", timeout=5)

        cmd = mock_popen.call_args.args[0]
        assert "--system-prompt-file" not in cmd
