import inspect

import pr_agent.cli as pr_agent_cli
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
