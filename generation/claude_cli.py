"""Shared Claude Code CLI runner for the pipeline's headless generation and
screening calls.

These are pure text/JSON generation calls, but historically each call site
re-implemented the same `subprocess.run` invocation and each carried the same
three reliability bugs. They are centralised here:

1. **Tools + MCP are disabled per call.** Leaving the interactive agent's tools
   (Bash/Read/WebFetch/…) and the user's MCP servers enabled lets the model take
   an agentic detour ("the workflow requires approval — generating the JSON
   directly instead…") and prepend that commentary to the output, which breaks
   strict JSON parsing. Disabling them yields a clean single-pass JSON response
   and avoids spawning/health-checking MCP servers. We pass ``--tools ""``
   rather than ``--disallowedTools <list>`` — the latter blocks tool *calls*
   but still loads every tool schema into context (confirmed via
   ``--output-format stream-json`` reporting ``tools=20`` under the old flag),
   which was also responsible for ~42% of calls silently paying for a second
   full-context turn (a denied-tool-call round trip). ``--tools ""`` makes that
   structurally impossible.

2. **On timeout the whole CLI process *tree* is killed.** ``claude`` launches a
   Node subtree; ``subprocess.run(timeout=…)`` only terminates the direct child,
   so on a timeout the Node children leak as orphans that pile up across a
   multi-job run and starve later calls. We kill the tree explicitly.

3. **One automatic retry** on timeout / non-zero exit / empty output, so a single
   slow call does not fail the whole job.

All calls force the Max-subscription path by purging ``ANTHROPIC_API_KEY`` from
the subprocess env (never pay-per-token API credits).

Every call runs with ``--output-format json`` instead of ``text`` so we can pull
token usage and a locally-estimated cost out of the response envelope (the
``result`` field carries the same text ``--output-format text`` used to return
directly, so callers and ``extract_json()`` are unaffected). Each call logs one
row to the ``claude_usage`` SQLite table via ``purpose`` (e.g. "screening",
"generation", "verification") for later reporting — see ``usage_report.py``.
Note: this usage/cost figure is a local estimate for visibility only, not an
authoritative bill, and Claude Code does not expose Max-plan rate-limit
percentage to headless calls at all — check that with the interactive
``/usage`` command in a real ``claude`` session.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile

from config import CLAUDE_CLI, DB_FILE

logger = logging.getLogger(__name__)

_EMPTY_MCP_CONFIG = '{"mcpServers":{}}'  # --strict-mcp-config + this => no MCP servers loaded


def _kill_tree(proc: "subprocess.Popen") -> None:
    """Kill the CLI process and its entire child subtree.

    ``claude`` spawns a Node subtree; killing only the parent (what
    ``Popen.kill`` does) leaves the children running as orphans that accumulate
    across a run and starve later calls. ``taskkill /T`` walks the tree on
    Windows; ``killpg`` does it on POSIX (the process is started in its own
    session/group below)."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _parse_envelope(raw: str) -> tuple[str | None, dict | None]:
    """Parse a ``--output-format json`` response envelope.

    Returns ``(result_text, usage_info)``. ``usage_info`` is ``None`` when the
    envelope can't be parsed as the expected JSON object — in that case
    ``result_text`` falls back to the raw stdout so callers behave exactly as
    they did under ``--output-format text`` (no usage is logged for that call).
    """
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        return raw, None
    if not isinstance(envelope, dict):
        return raw, None

    usage = envelope.get("usage") or {}
    usage_info = {
        "input_tokens": usage.get("input_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or 0,
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0) or 0,
        "cost_usd": envelope.get("total_cost_usd", envelope.get("cost_usd")),
        "duration_ms": envelope.get("duration_ms"),
        "num_turns": envelope.get("num_turns"),
    }
    if envelope.get("is_error"):
        return None, usage_info
    return envelope.get("result"), usage_info


def _log_usage(*, purpose: str, label: str, model: str, usage: dict) -> None:
    """Best-effort usage log — failures here must never break a generation call."""
    try:
        from db.database import Database
        db = Database(DB_FILE)
        db.initialize()
        db.log_claude_usage(purpose=purpose, label=label, model=model, **usage)
        db.close()
    except Exception:
        logger.debug("Failed to log Claude usage (non-fatal)", exc_info=True)


def run_claude(
    prompt: str, *, model: str, timeout: int,
    label: str = "Claude CLI", retries: int = 1,
    purpose: str = "other",
    system_prompt: str | None = None,
    disable_thinking: bool = False,
    thinking_budget_tokens: int | None = None,
) -> str | None:
    """Run one headless Claude CLI call with ``prompt`` piped on stdin.

    Returns the response text on success, or ``None`` if every attempt failed
    or timed out. ``retries`` is the number of *extra* attempts after the
    first. ``purpose`` tags the usage row logged for this call (e.g.
    "screening", "generation", "verification") — see ``usage_report.py``.

    ``system_prompt``, when given, is written to its own temp file and passed
    via ``--system-prompt-file`` instead of being concatenated into ``prompt``.
    Content piped on stdin is billed as cache-*creation* on every call and
    never reused; content passed via ``--system-prompt-file`` is cached
    server-side (keyed on content, not the temp path — so a fresh file per
    call is fine) with a 1h TTL and comes back as cheap cache-*read* on
    repeat calls with the same system prompt. Callers should build the same
    system prompt text across calls in a run (e.g. once per profile load) to
    actually hit that cache.

    ``disable_thinking``, when True, sets ``MAX_THINKING_TOKENS=0`` for this
    subprocess call only — extended thinking is ~86% of a generation call's
    billed output and is discarded, never surfaced to callers. Screening
    callers should NOT set this: measured verdict-flip rate with thinking off
    is ~37%, skewed lenient — the token saving isn't worth degraded verdicts
    there.

    ``thinking_budget_tokens``, when set (and ``disable_thinking`` is False),
    CAPS rather than disables extended thinking via
    ``MAX_THINKING_TOKENS=<value>`` — the model still reasons, it just can't
    exceed this many thinking tokens on a call. This is a gentler lever than
    ``disable_thinking``: a cap set above the typical/median thinking length
    for a call type leaves most calls completely untouched and only trims the
    minority that would have run longer, instead of removing thinking from
    every call. Ignored if ``disable_thinking=True``.
    """
    env = os.environ.copy()
    env["CLAUDECODE"] = "1"
    env.pop("ANTHROPIC_API_KEY", None)  # force Max subscription, not pay-per-token API
    if disable_thinking:
        env["MAX_THINKING_TOKENS"] = "0"
    elif thinking_budget_tokens is not None:
        env["MAX_THINKING_TOKENS"] = str(thinking_budget_tokens)

    cmd = [
        CLAUDE_CLI, "-p", "--output-format", "json", "--model", model,
        "--strict-mcp-config", "--mcp-config", _EMPTY_MCP_CONFIG,
        "--tools", "",
    ]

    for attempt in range(1, retries + 2):  # 1 initial try + `retries` retries
        tmp_path = None
        sys_tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(prompt)
                tmp_path = tmp.name

            call_cmd = list(cmd)
            if system_prompt:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".md", delete=False, encoding="utf-8"
                ) as sys_tmp:
                    sys_tmp.write(system_prompt)
                    sys_tmp_path = sys_tmp.name
                call_cmd += ["--system-prompt-file", sys_tmp_path]

            popen_kwargs: dict = {}
            if sys.platform != "win32":
                popen_kwargs["start_new_session"] = True  # own process group for killpg

            with open(tmp_path, encoding="utf-8") as stdin_file:
                proc = subprocess.Popen(
                    call_cmd, stdin=stdin_file,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding="utf-8", errors="replace", env=env, **popen_kwargs,
                )
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    _kill_tree(proc)
                    try:
                        proc.communicate(timeout=10)  # reap + drain pipes after the kill
                    except Exception:
                        pass
                    logger.error(f"{label} timed out after {timeout}s (attempt {attempt})")
                    continue

            if proc.returncode != 0:
                logger.error(
                    f"{label} error (rc={proc.returncode}): "
                    f"stderr={(stderr or '')[:500]!r}  stdout={(stdout or '')[:300]!r}"
                )
                continue
            if stdout and stdout.strip():
                result_text, usage = _parse_envelope(stdout)
                if usage is not None:
                    _log_usage(purpose=purpose, label=label, model=model, usage=usage)
                if result_text and result_text.strip():
                    return result_text
            logger.error(f"{label} returned empty output (attempt {attempt})")
        except FileNotFoundError:
            logger.error(f"Claude CLI not found at '{CLAUDE_CLI}'")
            return None  # missing binary won't fix itself on retry
        finally:
            for p in (tmp_path, sys_tmp_path):
                if p:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
    return None


def extract_json(text: str):
    """Parse a JSON value from a CLI response that may be fenced or preceded by
    commentary. Returns the parsed object/array, or ``None`` if none is found.

    Generation prompts ask for raw JSON, but the model occasionally wraps it in a
    ```json fence or prepends a sentence. We strip a fence if present, try a
    direct parse, and otherwise scan for the first balanced ``{...}`` / ``[...]``
    span (quote- and escape-aware)."""
    if not text:
        return None
    text = text.strip()

    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        text = m.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    candidates = [i for i in (text.find('{'), text.find('[')) if i != -1]
    if not candidates:
        return None
    start = min(candidates)
    opener = text[start]
    closer = '}' if opener == '{' else ']'

    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None
