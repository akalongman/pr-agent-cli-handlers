"""Define the one exception type every CLI handler failure raises."""


class CliHandlerError(RuntimeError):
    """Signal a failed CLI-backed call; raise it (never swallow it) so retry_with_fallback_models moves on."""
