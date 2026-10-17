"""Define the one exception type every CLI handler failure raises."""
from pr_agent.algo.token_budget import FallbackEligibleError


class CliHandlerError(RuntimeError, FallbackEligibleError):
    """Signal a failed CLI-backed call; raise it (never swallow it) so retry_with_fallback_models moves on.

    Subclass FallbackEligibleError: PR-Agent's fallback loop re-raises any error outside its allowlist at once.
    """
