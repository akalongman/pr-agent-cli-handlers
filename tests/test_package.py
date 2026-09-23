from importlib.metadata import version

import pr_agent_cli_handlers
from pr_agent_cli_handlers.errors import CliHandlerError


def test_package_version_matches_the_distribution_metadata():
    assert pr_agent_cli_handlers.__version__ == version("pr-agent-cli-handlers") == "0.1.0"


def test_cli_handler_error_is_a_runtime_error():
    assert issubclass(CliHandlerError, RuntimeError)


def test_pr_agent_dependency_exposes_the_agent_seam():
    from pr_agent.agent.pr_agent import PRAgent

    assert "ai_handler" in PRAgent.__init__.__code__.co_varnames
