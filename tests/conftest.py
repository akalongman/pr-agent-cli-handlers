import os

import pytest

# Keep LiteLLM from fetching its remote price map when pr_agent is imported, as PR-Agent's own CI does.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


@pytest.fixture(autouse=True)
def _clear_handler_environment(monkeypatch):
    """Remove PR_AGENT_CLI_* variables so the developer's shell cannot change test results."""
    for name in list(os.environ):
        if name.startswith("PR_AGENT_CLI_"):
            monkeypatch.delenv(name)
