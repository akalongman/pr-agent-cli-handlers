from pathlib import Path

import pr_agent

from pr_agent_cli_handlers.seam_scan import drift, main


def test_installed_pr_agent_matches_the_activation_table():
    assert drift(Path(pr_agent.__file__).parent) == []


def test_drift_reports_new_and_missing_seams_and_direct_calls(tmp_path):
    package = tmp_path / "pr_agent"
    (package / "tools").mkdir(parents=True)
    (package / "tools" / "pr_new.py").write_text(
        "class PRNew:\n"
        "    def __init__(self, pr_url, ai_handler=LiteLLMAIHandler):\n"
        "        self.ai_handler = ai_handler\n"
    )
    (package / "direct.py").write_text("handler = LiteLLMAIHandler()\n")

    messages = drift(package)

    assert "new seam not handled: pr_agent.tools.pr_new.PRNew.__init__" in messages
    assert "seam gone: pr_agent.agent.pr_agent.PRAgent.__init__" in messages
    assert "new direct LiteLLMAIHandler() call: pr_agent/direct.py" in messages
    assert "direct LiteLLMAIHandler() call gone: pr_agent/mosaico/executor.py" in messages
    assert main([str(package)]) == 1


def test_main_passes_on_the_installed_pr_agent():
    assert main([]) == 0
