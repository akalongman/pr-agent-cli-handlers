"""Point PR-Agent's AI handler defaults at a CLI-backed handler for the current process.

PR-Agent has no configuration switch for the AI handler: PRAgent and each tool class take an
``ai_handler`` factory whose default is LiteLLMAIHandler, and the entrypoints construct them with that
default (the GitHub Action runner constructs PRReviewer, PRDescription and PRCodeSuggestions directly).
Check that every such default still has that shape, then replace it.
"""
import importlib
import inspect
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Mapping

from pr_agent_cli_handlers.environment import HANDLER_VAR


@dataclass(frozen=True)
class Seam:
    module: str
    qualname: str
    required: bool


# Keep in step with seam_scan: it fails when PR-Agent gains or loses one of these.
SEAMS = (
    Seam("pr_agent.agent.pr_agent", "PRAgent", True),
    Seam("pr_agent.tools.pr_reviewer", "PRReviewer", True),
    Seam("pr_agent.tools.pr_description", "PRDescription", True),
    Seam("pr_agent.tools.pr_code_suggestions", "PRCodeSuggestions", True),
    Seam("pr_agent.tools.pr_questions", "PRQuestions", False),
    Seam("pr_agent.tools.pr_line_questions", "PR_LineQuestions", False),
    Seam("pr_agent.tools.pr_update_changelog", "PRUpdateChangelog", False),
    Seam("pr_agent.tools.pr_add_docs", "PRAddDocs", False),
    Seam("pr_agent.tools.pr_generate_labels", "PRGenerateLabels", False),
    Seam("pr_agent.tools.pr_help_message", "PRHelpMessage", False),
    Seam("pr_agent.tools.pr_help_docs", "PRHelpDocs", False),
)
# Construct LiteLLMAIHandler() directly in these files; they stay outside the supported surface.
DIRECT_CONSTRUCTIONS = ("pr_agent/doctor.py", "pr_agent/mosaico/executor.py")

HANDLERS = {
    "claude_code": ("pr_agent_cli_handlers.claude_code", "ClaudeCodeAIHandler"),
    "codex": ("pr_agent_cli_handlers.codex", "CodexAIHandler"),
}


class ActivationError(RuntimeError):
    """Stop before PR-Agent starts: the handler choice is invalid or a required seam is missing."""


def pr_agent_version() -> str:
    """Return the installed PR-Agent version, or "unknown"."""
    try:
        return version("pr-agent")
    except PackageNotFoundError:
        return "unknown"


def select_handler(environ: Mapping[str, str]):
    """Return the handler class PR_AGENT_CLI_HANDLER names."""
    name = environ.get(HANDLER_VAR, "").strip()
    if name not in HANDLERS:
        shown = repr(name) if name else "unset"
        raise ActivationError(f"{HANDLER_VAR} must be one of {', '.join(sorted(HANDLERS))}; it is {shown}")
    module_name, class_name = HANDLERS[name]
    return getattr(importlib.import_module(module_name), class_name)


def _replaceable(default) -> bool:
    """Return whether ``default`` is LiteLLMAIHandler or a handler an earlier activation installed."""
    from pr_agent.algo.ai_handlers.litellm_ai_handler import LiteLLMAIHandler

    from pr_agent_cli_handlers.base import CliAIHandler

    return default is LiteLLMAIHandler or (isinstance(default, type) and issubclass(default, CliAIHandler))


def _default_slot(init):
    """Return where ``init`` keeps its ai_handler default, ("positional", index) or ("keyword", name), or None."""
    try:
        parameters = inspect.signature(init).parameters
    except (TypeError, ValueError):
        return None
    parameter = parameters.get("ai_handler")
    if parameter is None or not _replaceable(parameter.default):
        return None
    if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
        return ("keyword", "ai_handler")
    with_defaults = [
        p for p in parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and p.default is not inspect.Parameter.empty
    ]
    return ("positional", with_defaults.index(parameter))


def activate(handler_cls) -> list[str]:
    """Replace every seam's ai_handler default with ``handler_cls``; return warnings for optional seams.

    Check every seam before replacing any default, so a missing required seam leaves PR-Agent untouched.
    """
    targets = []
    warnings = []
    for seam in SEAMS:
        try:
            init = getattr(importlib.import_module(seam.module), seam.qualname).__init__
        except (ImportError, AttributeError) as e:
            slot, reason = None, f"{type(e).__name__}: {e}"
        else:
            slot, reason = _default_slot(init), "no ai_handler parameter defaulting to LiteLLMAIHandler"
        if slot is None:
            message = f"{seam.module}.{seam.qualname}: {reason} (pr-agent {pr_agent_version()})"
            if seam.required:
                raise ActivationError(f"unsupported PR-Agent version: {message}")
            warnings.append(message)
            continue
        targets.append((init, slot))
    for init, (kind, where) in targets:
        if kind == "keyword":
            init.__kwdefaults__ = {**init.__kwdefaults__, where: handler_cls}
        else:
            defaults = list(init.__defaults__)
            defaults[where] = handler_cls
            init.__defaults__ = tuple(defaults)
    return warnings
