"""AI client abstraction.

The deployed app drives generation through the Codex CLI using georg's
ChatGPT/Codex subscription (`CodexCliClient`). Claude Code remains behind the
same interface as an inactive rollback backend.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

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
        schema: dict[str, Any] | None = None,
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
        self.default_timeout = settings.ai_timeout

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


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class CodexCliClient(AIClient):
    """Shells out to `codex exec` using persisted Codex CLI auth.

    The production service user must be logged in with ChatGPT/Codex subscription
    auth under CODEX_HOME. No OpenAI API key or Anthropic key is used here.
    """

    def __init__(self, settings: Settings):
        self.bin = settings.codex_bin
        self.model = settings.codex_model
        self.codex_home = settings.codex_home
        self.default_timeout = settings.ai_timeout

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        files: list[str] | None = None,
        timeout: int | None = None,
    ) -> str:
        return self._complete(
            prompt,
            system=system,
            files=files,
            timeout=timeout,
            schema_path=None,
        )

    def complete_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        files: list[str] | None = None,
        timeout: int | None = None,
        schema: dict[str, Any] | None = None,
    ) -> dict:
        if schema is None:
            return super().complete_json(
                prompt, system=system, files=files, timeout=timeout, schema=schema
            )

        schema_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".schema.json", delete=False, encoding="utf-8"
            ) as fh:
                json.dump(schema, fh, ensure_ascii=False)
                schema_path = Path(fh.name)
            raw = self._complete(
                prompt,
                system=system,
                files=files,
                timeout=timeout,
                schema_path=schema_path,
            )
        finally:
            if schema_path is not None:
                try:
                    schema_path.unlink()
                except OSError:
                    pass

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AIError(f"Invalid JSON from Codex CLI: {exc}") from exc
        if not isinstance(payload, dict):
            raise AIError("Invalid JSON from Codex CLI: expected an object")
        return payload

    def _complete(
        self,
        prompt: str,
        *,
        system: str | None,
        files: list[str] | None,
        timeout: int | None,
        schema_path: Path | None,
    ) -> str:
        full_prompt = f"{system.strip()}\n\n---\n\n{prompt}" if system else prompt

        resolved_files = [Path(f).resolve() for f in files or []]
        images = [str(p) for p in resolved_files if p.suffix.lower() in _IMAGE_SUFFIXES]
        if resolved_files:
            names = ", ".join(p.name for p in resolved_files)
            full_prompt += f"\n\nFiles you can read in the current directory: {names}"
            cwd = str(resolved_files[0].parent)
            return self._run_codex(
                full_prompt,
                cwd=cwd,
                images=images,
                schema_path=schema_path,
                timeout=timeout,
            )

        with tempfile.TemporaryDirectory(prefix="jobsapp-codex-") as tmp_dir:
            return self._run_codex(
                full_prompt,
                cwd=tmp_dir,
                images=images,
                schema_path=schema_path,
                timeout=timeout,
            )

    def _run_codex(
        self,
        prompt: str,
        *,
        cwd: str,
        images: list[str],
        schema_path: Path | None,
        timeout: int | None,
    ) -> str:
        cmd = [
            self.bin,
            "--ask-for-approval",
            "never",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--ignore-user-config",
            "--ignore-rules",
        ]
        if self.model:
            cmd += ["--model", self.model]
        if schema_path is not None:
            cmd += ["--output-schema", str(schema_path)]
        for image in images:
            cmd += ["--image", image]
        cmd.append("-")

        env = dict(os.environ)
        if self.codex_home:
            env["CODEX_HOME"] = self.codex_home

        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout or self.default_timeout,
                cwd=cwd,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise AIError("Codex CLI timed out") from exc
        except FileNotFoundError as exc:
            raise AIError(
                f"Codex CLI binary not found at {self.bin!r}. Install it and set CODEX_BIN."
            ) from exc

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:500]
            raise AIError(f"Codex CLI exited {proc.returncode}: {detail}")

        stdout = proc.stdout.strip()
        if not stdout:
            raise AIError("Empty output from Codex CLI")
        return stdout


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


def get_ai_client(settings: Settings | None = None) -> AIClient:
    settings = settings or get_settings()
    if settings.ai_backend == "codex_cli":
        return CodexCliClient(settings)
    if settings.ai_backend == "claude_code":
        return ClaudeCodeClient(settings)
    raise AIError(
        f"Unsupported AI_BACKEND={settings.ai_backend!r}. Use 'codex_cli' or 'claude_code'."
    )
