"""Run PR-Agent's CLI, or its GitHub Action runner, through the CLI handler PR_AGENT_CLI_HANDLER selects."""
import os
import sys
from typing import Optional

from pr_agent_cli_handlers.activation import ActivationError, activate, select_handler
from pr_agent_cli_handlers.errors import CliHandlerError

PROG = "pr-agent-cli-handlers"


def main(argv: Optional[list[str]] = None) -> int:
    """Activate the selected handler, then run ``pr-agent`` with ``argv``, or the Action runner for "action"."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        handler_cls = select_handler(os.environ)
        handler_cls()  # Validate the handler's environment settings before PR-Agent starts.
        warnings = activate(handler_cls)
    except (ActivationError, CliHandlerError) as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 2
    for warning in warnings:
        print(f"{PROG}: warning: {warning}", file=sys.stderr)
    if args[:1] == ["action"]:
        from pr_agent.servers import github_action_runner

        github_action_runner.main()
        return 0
    from pr_agent import cli as pr_agent_cli

    return pr_agent_cli.run(inargs=args) or 0


def entrypoint() -> None:
    sys.exit(main())
