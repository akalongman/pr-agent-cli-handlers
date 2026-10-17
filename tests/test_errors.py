import copy

from pr_agent.algo.pr_processing import retry_with_fallback_models
from pr_agent.config_loader import get_settings
from starlette_context import request_cycle_context

from pr_agent_cli_handlers.errors import CliHandlerError


async def test_a_cli_handler_error_moves_pr_agent_to_the_fallback_model():
    # Change a copy of the settings, as PR-Agent's CLI does per invocation, so the global settings stay untouched.
    settings = copy.deepcopy(get_settings())
    settings.set("config.model", "first-model")
    settings.set("config.fallback_models", ["second-model"])
    calls = []

    async def predict(model):
        calls.append(model)
        if model == "first-model":
            raise CliHandlerError("EchoHandler: echo-bin returned an empty answer")
        return f"answer from {model}"

    scope = request_cycle_context({"settings": settings})
    scope.__enter__()
    try:
        result = await retry_with_fallback_models(predict)
    finally:
        # Exit explicitly: request_cycle_context skips its reset when an exception crosses its bare yield.
        scope.__exit__(None, None, None)

    assert calls == ["first-model", "second-model"]
    assert result == "answer from second-model"
