from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.services import ai_client


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_get_ai_client_uses_codex_cli_by_default():
    client = ai_client.get_ai_client(make_settings())

    assert isinstance(client, ai_client.CodexCliClient)


def test_get_ai_client_keeps_claude_code_rollback():
    client = ai_client.get_ai_client(make_settings(ai_backend="claude_code"))

    assert isinstance(client, ai_client.ClaudeCodeClient)


def test_get_ai_client_rejects_anthropic_api():
    with pytest.raises(ai_client.AIError, match="Unsupported AI_BACKEND"):
        ai_client.get_ai_client(make_settings(ai_backend="anthropic_api"))


def test_codex_cli_complete_uses_safe_exec_and_stdin(monkeypatch, tmp_path):
    calls: list[dict] = []

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, 0, stdout="plain result\n", stderr="")

    monkeypatch.setattr(ai_client.subprocess, "run", fake_run)
    client = ai_client.CodexCliClient(
        make_settings(
            codex_bin="codex-test",
            codex_model="gpt-5-test",
            codex_home=str(tmp_path / "codex-home"),
            ai_timeout=11,
        )
    )

    result = client.complete("hello", system="system rules")

    assert result == "plain result"
    call = calls[0]
    cmd = call["cmd"]
    assert cmd[0:2] == ["codex-test", "exec"]
    assert "-" in cmd
    for expected in (
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--ask-for-approval",
        "never",
        "--ignore-user-config",
        "--ignore-rules",
        "--model",
        "gpt-5-test",
    ):
        assert expected in cmd
    assert call["input"] == "system rules\n\n---\n\nhello"
    assert call["timeout"] == 11
    assert call["env"]["CODEX_HOME"] == str(tmp_path / "codex-home")


def test_codex_cli_complete_json_uses_schema_and_parses_output(monkeypatch):
    calls: list[dict] = []

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, **kwargs})
        schema_path = Path(cmd[cmd.index("--output-schema") + 1])
        assert json.loads(schema_path.read_text(encoding="utf-8")) == {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        }
        return subprocess.CompletedProcess(cmd, 0, stdout='{"name":"Ada"}\n', stderr="")

    monkeypatch.setattr(ai_client.subprocess, "run", fake_run)
    client = ai_client.CodexCliClient(make_settings())

    result = client.complete_json(
        "return json",
        schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    )

    assert result == {"name": "Ada"}
    assert "--output-schema" in calls[0]["cmd"]


def test_codex_cli_complete_attaches_images(monkeypatch, tmp_path):
    image = tmp_path / "posting.png"
    image.write_bytes(b"fake image")
    calls: list[dict] = []

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, 0, stdout="transcribed\n", stderr="")

    monkeypatch.setattr(ai_client.subprocess, "run", fake_run)
    client = ai_client.CodexCliClient(make_settings())

    assert client.complete("read it", files=[str(image)]) == "transcribed"
    cmd = calls[0]["cmd"]
    assert "--image" in cmd
    assert str(image.resolve()) in cmd
    assert calls[0]["cwd"] == str(tmp_path.resolve())


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (subprocess.TimeoutExpired(cmd=["codex"], timeout=1), "Codex CLI timed out"),
        (FileNotFoundError("missing"), "Codex CLI binary not found"),
    ],
)
def test_codex_cli_complete_wraps_subprocess_exceptions(monkeypatch, exc, message):
    def fake_run(cmd, **kwargs):
        raise exc

    monkeypatch.setattr(ai_client.subprocess, "run", fake_run)
    client = ai_client.CodexCliClient(make_settings())

    with pytest.raises(ai_client.AIError, match=message):
        client.complete("hello")


@pytest.mark.parametrize(
    ("proc", "message"),
    [
        (subprocess.CompletedProcess(["codex"], 2, stdout="", stderr="bad auth"), "exited 2"),
        (subprocess.CompletedProcess(["codex"], 0, stdout="   ", stderr=""), "Empty output"),
        (subprocess.CompletedProcess(["codex"], 0, stdout="{not json", stderr=""), "Invalid JSON"),
    ],
)
def test_codex_cli_complete_json_reports_bad_outputs(monkeypatch, proc, message):
    def fake_run(cmd, **kwargs):
        return proc

    monkeypatch.setattr(ai_client.subprocess, "run", fake_run)
    client = ai_client.CodexCliClient(make_settings())

    with pytest.raises(ai_client.AIError, match=message):
        client.complete_json("hello", schema={"type": "object"})
