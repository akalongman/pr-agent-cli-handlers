import json
import os
from types import SimpleNamespace

import pytest

import pr_agent_cli_handlers.base as cli_module
from pr_agent_cli_handlers.agy import AgyAIHandler
from pr_agent_cli_handlers.errors import CliHandlerError


class _FakeSettings:
    def __init__(self, values=None):
        self.values = values or {}
        self.config = SimpleNamespace(ai_timeout=30)

    def get(self, key, default=None):
        return self.values.get(key, default)


def _install_settings(monkeypatch, values=None):
    monkeypatch.setattr(cli_module, "get_settings", lambda: _FakeSettings(values))


def _lines(*events):
    return "\n".join(json.dumps(event) for event in events) + "\n"


def _result(**overrides):
    result = {"conversation_id": "c1", "status": "SUCCESS", "response": "review text\n",
              "usage": {"input_tokens": 12605, "output_tokens": 25, "thinking_tokens": 24, "total_tokens": 12630}}
    result.update(overrides)
    return {"event": "result", "result": result}


def test_build_command_uses_stream_json_on_stdin_in_an_empty_workdir(monkeypatch):
    _install_settings(monkeypatch, {"CONFIG.REASONING_EFFORT": "medium"})
    monkeypatch.setenv("PR_AGENT_CLI_EXTRA_ARGS", "--log-file /tmp/agy.log")
    handler = AgyAIHandler()

    command = handler.build_command("gemini-3.8-flash-high", "SYS", "USER")

    assert command.argv == [
        "agy", "--disable-slash-commands", "--sandbox", "--input-format", "stream-json", "--output-format",
        "stream-json", "--model", "gemini-3.8-flash-high", "--log-file", "/tmp/agy.log",
    ]
    assert json.loads(command.stdin) == {"event": "user", "message": {"content": "SYS\n\nUSER"}}
    assert command.stdin.endswith("\n")
    assert command.cwd == handler.workdir


@pytest.mark.parametrize("effort", [None, "none", "minimal", "low", "medium", "high", "xhigh", "max", "turbo"])
def test_build_command_never_passes_effort(monkeypatch, effort):
    _install_settings(monkeypatch, {"CONFIG.REASONING_EFFORT": effort})
    for model in ("gemini-3.8-flash-high", "claude-sonnet-4-6"):
        assert "--effort" not in AgyAIHandler().build_command(model, "S", "U").argv


def test_parse_response_reads_the_result_line(monkeypatch):
    _install_settings(monkeypatch)
    stdout = _lines({"event": "step_update", "step_update": {"state": "DONE"}}, _result())

    response = AgyAIHandler().parse_response(stdout)

    assert (response.text, response.prompt_tokens, response.completion_tokens) == ("review text\n", 12605, 25)
    assert response.cost_usd is None


def test_parse_response_uses_the_last_result_line(monkeypatch):
    _install_settings(monkeypatch)
    stdout = _lines(_result(response="first"), {"event": "result", "result": "not-a-dict"}, None, 42,
                    _result(response="last"))

    assert AgyAIHandler().parse_response(stdout).text == "last"


def test_parse_response_raises_without_a_result_line(monkeypatch):
    _install_settings(monkeypatch)
    with pytest.raises(CliHandlerError, match="no result"):
        AgyAIHandler().parse_response(_lines({"event": "step_update"}) + "not json\n")


def test_parse_response_raises_on_a_failed_status(monkeypatch):
    _install_settings(monkeypatch)
    with pytest.raises(CliHandlerError, match="ERROR: quota exhausted"):
        AgyAIHandler().parse_response(_lines(_result(status="ERROR", error="quota exhausted", response="")))


def test_agy_names_its_credential_variable():
    assert AgyAIHandler.credential_env == {"GEMINI_API_KEY"}
    assert AgyAIHandler.config_env == frozenset()


async def test_contract_runs_the_agy_binary_in_its_workdir(monkeypatch, fake_cli):
    _install_settings(monkeypatch)
    record = fake_cli("agy", _lines(_result(response="looks good")))
    handler = AgyAIHandler()

    text, finish_reason = await handler.chat_completion(model="gemini-3.8-flash-high", system="SYS", user="USER")

    recorded = json.loads(record.read_text())
    assert (text, finish_reason) == ("looks good", "stop")
    assert recorded["argv"] == handler.build_command("gemini-3.8-flash-high", "SYS", "USER").argv[1:]
    assert json.loads(recorded["stdin"]) == {"event": "user", "message": {"content": "SYS\n\nUSER"}}
    assert os.path.realpath(recorded["cwd"]) == os.path.realpath(handler.workdir)


@pytest.mark.parametrize("response", ["", None, "  \n"])
async def test_contract_raises_on_an_empty_answer(monkeypatch, fake_cli, response):
    _install_settings(monkeypatch)
    fake_cli("agy", _lines(_result(response=response)))

    with pytest.raises(CliHandlerError, match="AgyAIHandler: agy returned an empty answer$"):
        await AgyAIHandler().chat_completion(model="gemini-3.8-flash-high", system="SYS", user="USER")
