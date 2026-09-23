import importlib
import inspect
import sys
import types

import pytest
from pr_agent.agent.pr_agent import PRAgent
from pr_agent.algo.ai_handlers.litellm_ai_handler import LiteLLMAIHandler

import pr_agent_cli_handlers.activation as activation
from pr_agent_cli_handlers.activation import ActivationError, Seam, activate, select_handler
from pr_agent_cli_handlers.claude_code import ClaudeCodeAIHandler
from pr_agent_cli_handlers.codex import CodexAIHandler


def _default_of(seam):
    init = getattr(importlib.import_module(seam.module), seam.qualname).__init__
    return inspect.signature(init).parameters["ai_handler"].default


@pytest.mark.parametrize("name, expected", [("claude_code", ClaudeCodeAIHandler), ("codex", CodexAIHandler)])
def test_select_handler_returns_the_named_adapter(name, expected):
    assert select_handler({"PR_AGENT_CLI_HANDLER": f" {name} "}) is expected


@pytest.mark.parametrize("value", [None, "", "  ", "litellm", "Claude_Code"])
def test_select_handler_rejects_unknown_or_unset_names(value):
    environ = {} if value is None else {"PR_AGENT_CLI_HANDLER": value}
    with pytest.raises(ActivationError, match="PR_AGENT_CLI_HANDLER must be one of claude_code, codex"):
        select_handler(environ)


def test_seam_table_lists_the_eleven_known_constructors():
    assert len(activation.SEAMS) == 11
    assert {(s.module, s.qualname) for s in activation.SEAMS if s.required} == {
        ("pr_agent.agent.pr_agent", "PRAgent"),
        ("pr_agent.tools.pr_reviewer", "PRReviewer"),
        ("pr_agent.tools.pr_description", "PRDescription"),
        ("pr_agent.tools.pr_code_suggestions", "PRCodeSuggestions"),
    }


def test_activate_replaces_every_seam_default(restore_seams):
    assert activate(ClaudeCodeAIHandler) == []

    assert all(_default_of(seam) is ClaudeCodeAIHandler for seam in activation.SEAMS)
    assert PRAgent().ai_handler is ClaudeCodeAIHandler


def test_activate_is_repeatable_and_can_switch_handlers(restore_seams):
    activate(ClaudeCodeAIHandler)
    activate(ClaudeCodeAIHandler)
    activate(CodexAIHandler)

    assert all(_default_of(seam) is CodexAIHandler for seam in activation.SEAMS)


def _install_fake_module(monkeypatch, name, cls):
    module = types.ModuleType(name)
    setattr(module, cls.__name__, cls)
    monkeypatch.setitem(sys.modules, name, module)


class _NoSeam:
    def __init__(self, pr_url, args=None):
        self.pr_url = pr_url


def test_missing_required_seam_raises_and_patches_nothing(monkeypatch, restore_seams):
    _install_fake_module(monkeypatch, "fake_seam_module", _NoSeam)
    monkeypatch.setattr(activation, "SEAMS", activation.SEAMS + (Seam("fake_seam_module", "_NoSeam", True),))

    with pytest.raises(ActivationError, match=r"unsupported PR-Agent version: fake_seam_module\._NoSeam"):
        activate(ClaudeCodeAIHandler)

    assert _default_of(activation.SEAMS[0]) is LiteLLMAIHandler


def test_missing_optional_seam_becomes_a_warning(monkeypatch, restore_seams):
    _install_fake_module(monkeypatch, "fake_seam_module", _NoSeam)
    monkeypatch.setattr(activation, "SEAMS", activation.SEAMS + (Seam("fake_seam_module", "_NoSeam", False),))

    warnings = activate(ClaudeCodeAIHandler)

    assert len(warnings) == 1 and "fake_seam_module._NoSeam" in warnings[0]
    assert PRAgent().ai_handler is ClaudeCodeAIHandler


def test_required_seam_import_failure_patches_nothing(monkeypatch, restore_seams):
    missing = Seam("pr_agent_cli_handlers_no_such_module", "Anything", True)
    monkeypatch.setattr(activation, "SEAMS", activation.SEAMS + (missing,))

    with pytest.raises(ActivationError, match="pr_agent_cli_handlers_no_such_module"):
        activate(ClaudeCodeAIHandler)

    assert _default_of(activation.SEAMS[0]) is LiteLLMAIHandler
