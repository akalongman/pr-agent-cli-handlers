from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PINS = {"@anthropic-ai/claude-code": "2.1.280", "@openai/codex": "0.156.1"}


def test_action_is_a_composite_action_with_the_documented_inputs():
    action = yaml.safe_load((ROOT / "action.yml").read_text())
    assert action["runs"]["using"] == "composite"
    assert set(action["inputs"]) == {"handler", "model", "cli-version", "package-version"}
    assert action["inputs"]["handler"]["required"] is True
    assert action["inputs"]["model"]["required"] is True
    run_steps = [step["run"] for step in action["runs"]["steps"] if "run" in step]
    assert any("pr-agent-cli-handlers action" in run for run in run_steps)


def test_gitlab_template_runs_on_merge_request_pipelines():
    template = yaml.safe_load((ROOT / "templates" / "gitlab-ci.yml").read_text())
    job = template["pr-agent-cli-handlers"]
    assert job["rules"] == [{"if": '$CI_PIPELINE_SOURCE == "merge_request_event"'}]
    assert job["image"] == "node:22-bookworm"
    script = "\n".join(job["script"])
    for command in ("describe", "review", "improve"):
        assert f'pr-agent-cli-handlers --pr_url="$MR_URL" {command}' in script


def test_action_and_template_pin_the_same_cli_versions():
    for path in (ROOT / "action.yml", ROOT / "templates" / "gitlab-ci.yml"):
        text = path.read_text()
        for package, pinned in PINS.items():
            assert f"{package}@${{CLI_VERSION:-{pinned}}}" in text, (path.name, package)


def test_readme_documents_every_environment_variable_and_handler():
    readme = (ROOT / "README.md").read_text()
    for name in ("PR_AGENT_CLI_HANDLER", "PR_AGENT_CLI_BINARY", "PR_AGENT_CLI_EXTRA_ARGS", "PR_AGENT_CLI_TIMEOUT",
                 "PR_AGENT_CLI_PASS_ENV", "claude_code", "codex"):
        assert name in readme
