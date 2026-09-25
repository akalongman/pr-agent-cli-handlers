import json
import os
from types import SimpleNamespace

import pytest

import pr_agent_cli_handlers.base as cli_module
from pr_agent_cli_handlers.claude_code import ClaudeCodeAIHandler
from pr_agent_cli_handlers.errors import CliHandlerError


class _FakeSettings:
    def __init__(self, values=None):
        self.values = values or {}
        self.config = SimpleNamespace(ai_timeout=30)

    def get(self, key, default=None):
        return self.values.get(key, default)


def _install_settings(monkeypatch, values=None):
    monkeypatch.setattr(cli_module, "get_settings", lambda: _FakeSettings(values))


def _success_payload(**overrides):
    payload = {
        "type": "result", "subtype": "success", "is_error": False, "result": "review text",
        "stop_reason": "end_turn", "total_cost_usd": 0,
        "usage": {"input_tokens": 400, "cache_creation_input_tokens": 50, "cache_read_input_tokens": 12,
                  "output_tokens": 30},
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_build_command_uses_the_restricted_headless_flag_set(monkeypatch):
    _install_settings(monkeypatch, {"CONFIG.REASONING_EFFORT": "xhigh"})
    monkeypatch.setenv("PR_AGENT_CLI_EXTRA_ARGS", "--verbose")
    handler = ClaudeCodeAIHandler()
    command = handler.build_command("claude-opus-5", "SYS", "USER")
    prompt_file = command.argv[command.argv.index("--system-prompt-file") + 1]

    assert command.argv == [
        "claude", "-p", "--restricted", "--safe-mode", "--strict-mcp-config", "--tools", "",
        "--no-session-persistence", "--output-format", "json", "--system-prompt-file", prompt_file,
        "--model", "claude-opus-5", "--effort", "xhigh", "--verbose",
    ]
    assert command.stdin == "USER"
    assert command.temp_files == [prompt_file]
    assert "SYS" not in command.argv
    assert os.path.dirname(prompt_file) == handler.prompt_dir
    with open(prompt_file, encoding="utf-8") as handle:
        assert handle.read() == "SYS"


def test_build_command_runs_in_one_empty_workdir_per_handler(monkeypatch):
    _install_settings(monkeypatch)
    handler = ClaudeCodeAIHandler()

    first = handler.build_command("claude-opus-5", "SYS", "USER")
    second = handler.build_command("claude-opus-5", "SYS", "USER")

    assert first.cwd == second.cwd == handler.workdir
    assert handler.prompt_dir != handler.workdir
    assert os.path.isdir(handler.workdir)
    assert os.listdir(handler.workdir) == []


def test_build_command_writes_a_new_prompt_file_per_call(monkeypatch):
    _install_settings(monkeypatch)
    handler = ClaudeCodeAIHandler()

    first = handler.build_command("claude-opus-5", "ONE", "USER").temp_files
    second = handler.build_command("claude-opus-5", "TWO", "USER").temp_files

    assert first != second
    assert sorted(os.listdir(handler.prompt_dir)) == sorted(os.path.basename(p) for p in first + second)


def test_prompt_dir_is_readable_by_its_owner_only(monkeypatch):
    _install_settings(monkeypatch)
    handler = ClaudeCodeAIHandler()
    assert os.stat(handler.prompt_dir).st_mode & 0o777 == 0o700


def test_build_command_leaves_no_prompt_file_when_reading_the_effort_fails(monkeypatch):
    _install_settings(monkeypatch)
    handler = ClaudeCodeAIHandler()

    def fail():
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(handler, "reasoning_effort", fail)

    with pytest.raises(RuntimeError, match="settings unavailable"):
        handler.build_command("claude-opus-5", "SYS", "USER")
    assert os.listdir(handler.prompt_dir) == []


def test_build_command_omits_effort_the_harness_does_not_accept(monkeypatch):
    _install_settings(monkeypatch, {"CONFIG.REASONING_EFFORT": "minimal"})
    command = ClaudeCodeAIHandler().build_command("claude-opus-5", "SYS", "USER")
    assert "--effort" not in command.argv


@pytest.mark.parametrize("given, expected", [
    ("anthropic/claude-opus-5", "claude-opus-5"),
    ("bedrock/anthropic.claude-sonnet-5", "claude-sonnet-5"),
    ("claude-opus-5", "claude-opus-5"),
    ("opus", "opus"),
])
def test_map_model_strips_provider_prefixes(monkeypatch, given, expected):
    _install_settings(monkeypatch)
    assert ClaudeCodeAIHandler().map_model(given) == expected


def test_map_model_rejects_non_claude_models(monkeypatch):
    _install_settings(monkeypatch)
    with pytest.raises(CliHandlerError, match="Claude models only"):
        ClaudeCodeAIHandler().map_model("gpt-5.6")


def test_parse_response_reads_text_usage_and_unknown_cost(monkeypatch):
    _install_settings(monkeypatch)
    response = ClaudeCodeAIHandler().parse_response(_success_payload())

    assert response.text == "review text"
    assert response.finish_reason == "stop"
    assert response.prompt_tokens == 462
    assert response.completion_tokens == 30
    assert response.cost_usd is None


def test_parse_response_maps_max_tokens_to_length_and_keeps_a_reported_cost(monkeypatch):
    _install_settings(monkeypatch)
    response = ClaudeCodeAIHandler().parse_response(_success_payload(stop_reason="max_tokens", total_cost_usd=0.25))
    assert response.finish_reason == "length"
    assert response.cost_usd == 0.25


def test_parse_response_raises_on_reported_error(monkeypatch):
    _install_settings(monkeypatch)
    with pytest.raises(CliHandlerError, match="Not logged in"):
        ClaudeCodeAIHandler().parse_response(_success_payload(is_error=True, result="Not logged in"))


def test_parse_response_names_the_subtype_when_no_result_is_reported(monkeypatch):
    _install_settings(monkeypatch)
    payload = json.loads(_success_payload(subtype="error_max_turns", is_error=True))
    del payload["result"]

    with pytest.raises(CliHandlerError) as exc_info:
        ClaudeCodeAIHandler().parse_response(json.dumps(payload))
    assert str(exc_info.value) == "Claude Code reported an error (error_max_turns)"


def test_parse_response_raises_on_non_json(monkeypatch):
    _install_settings(monkeypatch)
    with pytest.raises(CliHandlerError, match="JSON"):
        ClaudeCodeAIHandler().parse_response("plain text")


async def test_chat_completion_raises_cli_handler_error_on_non_numeric_usage(monkeypatch):
    _install_settings(monkeypatch)
    handler = ClaudeCodeAIHandler()

    async def fake_run(command):
        return _success_payload(usage={"input_tokens": 400, "output_tokens": "many"})

    monkeypatch.setattr(handler, "_run", fake_run)

    with pytest.raises(CliHandlerError, match="ClaudeCodeAIHandler") as exc_info:
        await handler.chat_completion(model="anthropic/claude-opus-5", system="s", user="u")
    assert isinstance(exc_info.value.__cause__, ValueError)


@pytest.mark.parametrize("result", [42, {"summary": "looks good"}], ids=["number", "object"])
async def test_chat_completion_raises_cli_handler_error_on_a_non_string_result(monkeypatch, result):
    _install_settings(monkeypatch)
    # Give redaction a credential to look for, so a number reaches the same path as in a real run.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-sentinel-key")
    handler = ClaudeCodeAIHandler()

    async def fake_run(command):
        return _success_payload(result=result)

    monkeypatch.setattr(handler, "_run", fake_run)

    with pytest.raises(CliHandlerError, match="ClaudeCodeAIHandler"):
        await handler.chat_completion(model="anthropic/claude-opus-5", system="s", user="u")


def test_claude_code_names_its_credential_and_config_variables():
    assert ClaudeCodeAIHandler.credential_env == {
        "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    }
    assert ClaudeCodeAIHandler.config_env == {
        "ANTHROPIC_BASE_URL", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
        "ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION", "GOOGLE_APPLICATION_CREDENTIALS", "AWS_REGION",
        "AWS_PROFILE",
    }


def test_child_env_keeps_the_subscription_token_and_drops_other_tokens(monkeypatch):
    _install_settings(monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-sentinel")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-sentinel-openai")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_sentinel_github")

    env = ClaudeCodeAIHandler().child_env()

    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat-sentinel"
    assert "OPENAI_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env


def test_child_env_disables_the_auto_updater(monkeypatch):
    _install_settings(monkeypatch)
    monkeypatch.delenv("DISABLE_AUTOUPDATER", raising=False)

    env = ClaudeCodeAIHandler().child_env()

    assert env["DISABLE_AUTOUPDATER"] == "1"


def test_child_env_keeps_the_auto_updater_disabled_over_a_passed_value(monkeypatch):
    _install_settings(monkeypatch)
    monkeypatch.setenv("DISABLE_AUTOUPDATER", "0")
    monkeypatch.setenv("PR_AGENT_CLI_PASS_ENV", "DISABLE_AUTOUPDATER")

    env = ClaudeCodeAIHandler().child_env()

    assert env["DISABLE_AUTOUPDATER"] == "1"


@pytest.mark.parametrize("model", ["--claude", "anthropic.--claude", "bedrock/anthropic.--claude"])
def test_map_model_rejects_a_flag_that_contains_claude(monkeypatch, model):
    _install_settings(monkeypatch)
    with pytest.raises(CliHandlerError, match="invalid model name"):
        ClaudeCodeAIHandler().map_model(model)


async def test_contract_runs_the_claude_binary_with_the_built_command(monkeypatch, fake_cli):
    _install_settings(monkeypatch)
    record = fake_cli("claude", _success_payload(result="looks good"))
    handler = ClaudeCodeAIHandler()

    text, finish_reason = await handler.chat_completion(model="anthropic/claude-opus-5", system="SYS", user="USER")

    recorded = json.loads(record.read_text())
    prompt_file = recorded["argv"][recorded["argv"].index("--system-prompt-file") + 1]
    assert (text, finish_reason) == ("looks good", "stop")
    assert os.path.dirname(prompt_file) == handler.prompt_dir
    assert recorded["system_prompt"] == "SYS"
    assert "SYS" not in recorded["argv"]
    assert recorded["stdin"] == "USER"
    assert recorded["cwd"] == handler.workdir
    assert recorded["cwd"] != os.getcwd()
    assert os.listdir(handler.prompt_dir) == []


async def test_contract_passes_a_system_prompt_larger_than_one_argument_allows(monkeypatch, fake_cli):
    _install_settings(monkeypatch)
    record = fake_cli("claude", _success_payload(result="ok"))
    # 200,000 bytes, above Linux's 131,072-byte limit for one argument.
    system = "rule line\n" * 20_000
    handler = ClaudeCodeAIHandler()

    await handler.chat_completion(model="claude-opus-5", system=system, user="USER")

    recorded = json.loads(record.read_text())
    assert recorded["system_prompt"] == system
    assert all(len(arg.encode("utf-8")) <= cli_module.MAX_ARGV_ELEMENT_BYTES for arg in recorded["argv"])
