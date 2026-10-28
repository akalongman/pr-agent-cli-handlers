import copy
import inspect
import json

import pr_agent.cli as pr_agent_cli
import pr_agent.config_loader as config_loader
import pr_agent.servers.github_action_runner as github_action_runner
from pr_agent.agent.pr_agent import PRAgent
from pr_agent.algo.ai_handlers.litellm_ai_handler import LiteLLMAIHandler

from pr_agent_cli_handlers.claude_code import ClaudeCodeAIHandler
from pr_agent_cli_handlers.cli import main


def _pragent_default():
    return inspect.signature(PRAgent.__init__).parameters["ai_handler"].default


def test_main_exits_2_when_the_handler_is_unset(capsys, restore_seams):
    assert main(["--pr_url", "x", "review"]) == 2
    assert "PR_AGENT_CLI_HANDLER" in capsys.readouterr().err
    assert _pragent_default() is LiteLLMAIHandler


def test_main_exits_2_on_invalid_handler_settings_before_activation(monkeypatch, capsys, restore_seams):
    monkeypatch.setenv("PR_AGENT_CLI_HANDLER", "codex")
    monkeypatch.setenv("PR_AGENT_CLI_TIMEOUT", "abc")

    assert main(["--pr_url", "x", "review"]) == 2
    assert "PR_AGENT_CLI_TIMEOUT" in capsys.readouterr().err
    assert _pragent_default() is LiteLLMAIHandler


def test_main_passes_arguments_to_pr_agent_cli_after_activation(monkeypatch, restore_seams):
    seen = {}

    def fake_run(inargs=None, args=None):
        seen["inargs"] = inargs
        seen["default"] = _pragent_default()

    monkeypatch.setattr(pr_agent_cli, "run", fake_run)
    monkeypatch.setenv("PR_AGENT_CLI_HANDLER", "claude_code")

    assert main(["--pr_url", "https://example.test/pr/1", "review"]) == 0
    assert seen == {"inargs": ["--pr_url", "https://example.test/pr/1", "review"], "default": ClaudeCodeAIHandler}


def test_main_returns_the_exit_code_of_pr_agent(monkeypatch, restore_seams):
    monkeypatch.setattr(pr_agent_cli, "run", lambda inargs=None, args=None: 1)
    monkeypatch.setenv("PR_AGENT_CLI_HANDLER", "claude_code")

    assert main(["--pr_url", "x", "review"]) == 1


def test_main_action_runs_the_github_action_runner(monkeypatch, restore_seams):
    calls = []
    monkeypatch.setattr(github_action_runner, "main", lambda: calls.append(_pragent_default()))
    monkeypatch.setenv("PR_AGENT_CLI_HANDLER", "claude_code")

    assert main(["action"]) == 0
    assert calls == [ClaudeCodeAIHandler]


def test_main_action_runs_the_tools_with_a_cli_login_and_no_provider_api_key(monkeypatch, tmp_path, restore_seams):
    """PR-Agent after 0.49.0 stops the runner when LiteLLM finds no key for the model's provider; the weekly
    upstream-main job runs this test against that code."""
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"action": "opened", "pull_request": {
        "html_url": "https://github.com/owner/repo/pull/1",
        "url": "https://api.github.com/repos/owner/repo/pulls/1"}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_TOKEN", "github-token-value")
    monkeypatch.setenv("PR_AGENT_CLI_HANDLER", "claude_code")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token-value")
    # The runner writes settings as it goes; give it a copy, as PR-Agent's GitHub App does per request.
    settings = copy.deepcopy(config_loader.global_settings)
    settings.set("config.model", "anthropic/claude-sonnet-5")  # the prefix names the provider, not LiteLLM's map
    monkeypatch.setattr(config_loader, "global_settings", settings)
    monkeypatch.setattr(github_action_runner, "setup_logger", lambda *args, **kwargs: None)
    monkeypatch.setattr(github_action_runner, "apply_repo_settings", lambda pr_url: None)
    ran = []

    def tool(name):
        class Tool:
            def __init__(self, pr_url):
                pass

            async def run(self):
                ran.append(name)

        return Tool

    for name in ("PRDescription", "PRReviewer", "PRCodeSuggestions"):
        monkeypatch.setattr(github_action_runner, name, tool(name))

    assert main(["action"]) == 0
    assert ran == ["PRDescription", "PRReviewer", "PRCodeSuggestions"]
