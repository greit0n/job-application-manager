"""AI client abstraction.

The deployed app drives generation through the Claude Code CLI using georg's
Max subscription (`ClaudeCodeClient`). The whole thing sits behind the
`AIClient` interface so we can swap to a pay-per-token Anthropic API key
(`AnthropicApiClient`) by flipping `AI_BACKEND` in config -- no call-site
changes -- if subscription limits or terms ever become a problem.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from ..config import Settings, get_settings


class AIError(RuntimeError):
    """Raised when the AI backend fails to produce a usable response."""


class AIClient(ABC):
    """Single-shot text/JSON completion. No chat state; each call is isolated."""

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        files: list[str] | None = None,
        timeout: int | None = None,
    ) -> str:
        """Return the model's text output for a single prompt.

        `files` are absolute paths the model may read (e.g. an uploaded job PDF
        or a screenshot). `system` is prepended as guidance.
        """

    def complete_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        files: list[str] | None = None,
        timeout: int | None = None,
    ) -> dict:
        """Like `complete`, but parse the first JSON object out of the output."""
        raw = self.complete(prompt, system=system, files=files, timeout=timeout)
        return extract_json(raw)


def extract_json(text: str) -> dict:
    """Pull the first balanced JSON object out of model output.

    The model is asked to return JSON, but may wrap it in prose or ```json
    fences. This is forgiving about that.
    """
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        start = text.find("{")
        if start == -1:
            raise AIError(f"No JSON object found in AI output: {text[:200]!r}")
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    break
        if candidate is None:
            raise AIError("Unbalanced JSON in AI output")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise AIError(f"Invalid JSON from AI: {exc}") from exc


class ClaudeCodeClient(AIClient):
    """Shells out to the Claude Code CLI in headless print mode.

    Auth comes from CLAUDE_CODE_OAUTH_TOKEN (issued by `claude setup-token`,
    tied to the Max subscription) passed through the subprocess environment.
    """

    def __init__(self, settings: Settings):
        self.bin = settings.claude_bin
        self.token = settings.claude_code_oauth_token
        self.model = settings.claude_model
        self.effort = settings.claude_effort
        self.default_timeout = settings.claude_timeout

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        files: list[str] | None = None,
        timeout: int | None = None,
    ) -> str:
        full_prompt = f"{system.strip()}\n\n---\n\n{prompt}" if system else prompt

        cwd: str | None = None
        if files:
            # Let the model read the referenced files; run inside their dir and
            # tell it the basenames it can Read (the prompt alone can't carry bytes).
            names = ", ".join(Path(f).name for f in files)
            full_prompt += f"\n\nFiles you can Read in the current directory: {names}"
            cwd = str(Path(files[0]).resolve().parent)

        cmd = [self.bin, "-p", full_prompt, "--output-format", "json"]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--effort", self.effort]
        if files:
            cmd += ["--allowedTools", "Read"]

        # Inherit the parent environment (HOME, PATH, XDG_* etc. - the CLI needs
        # them for its config/cache) and override only the auth token.
        env = dict(os.environ)
        if self.token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self.token

        try:
            proc = subprocess.run(
                cmd,
                input="",
                capture_output=True,
                text=True,
                timeout=timeout or self.default_timeout,
                cwd=cwd,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise AIError("Claude Code timed out") from exc
        except FileNotFoundError as exc:
            raise AIError(
                f"Claude Code binary not found at {self.bin!r}. Install it and set CLAUDE_BIN."
            ) from exc

        if proc.returncode != 0:
            raise AIError(
                f"Claude Code exited {proc.returncode}: {proc.stderr.strip()[:500]}"
            )

        return _parse_cli_result(proc.stdout)


def _parse_cli_result(stdout: str) -> str:
    """`claude -p --output-format json` prints an object with a `result` field."""
    stdout = stdout.strip()
    if not stdout:
        raise AIError("Empty output from Claude Code")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        # Fallback: some versions stream plain text on the last line.
        return stdout
    if isinstance(payload, dict):
        if payload.get("is_error"):
            raise AIError(f"Claude Code error: {payload.get('result', '')[:500]}")
        return str(payload.get("result", "")).strip() or stdout
    return stdout


def _system_path() -> str:
    import os

    return os.environ.get("PATH", "")


class AnthropicApiClient(AIClient):
    """Pay-per-token fallback via the Anthropic Messages API (httpx, no SDK dep).

    Text-only for now; document/image input would add base64 document blocks.
    """

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, settings: Settings):
        self.api_key = settings.anthropic_api_key
        self.model = settings.claude_model or "claude-opus-4-8"
        self.default_timeout = settings.claude_timeout

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        files: list[str] | None = None,
        timeout: int | None = None,
    ) -> str:
        if not self.api_key:
            raise AIError("ANTHROPIC_API_KEY is not set for the anthropic_api backend")
        import httpx

        body: dict = {
            "model": self.model,
            "max_tokens": 8000,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            resp = httpx.post(
                self.API_URL,
                json=body,
                headers=headers,
                timeout=timeout or self.default_timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIError(f"Anthropic API request failed: {exc}") from exc

        data = resp.json()
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        text = "".join(parts).strip()
        if not text:
            raise AIError("Empty response from Anthropic API")
        return text


def get_ai_client(settings: Settings | None = None) -> AIClient:
    settings = settings or get_settings()
    if settings.ai_backend == "anthropic_api":
        return AnthropicApiClient(settings)
    return ClaudeCodeClient(settings)
