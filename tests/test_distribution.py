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
    assert job["image"] == "node:24-trixie"
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


def _workflow(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())


def _setup_uv(job):
    return next(step for step in job["steps"] if step.get("uses", "").startswith("astral-sh/setup-uv@"))


def test_upstream_workflow_runs_weekly_against_pr_agent_main():
    workflow = _workflow("upstream-main.yml")
    triggers = workflow[True]  # YAML 1.1 reads the bare key "on" as a boolean.
    assert "schedule" in triggers and "workflow_dispatch" in triggers
    runs = [step.get("run", "") for step in workflow["jobs"]["upstream-main"]["steps"]]
    assert any("git+https://github.com/The-PR-Agent/pr-agent@main" in run for run in runs)
    assert any("python -m pr_agent_cli_handlers.seam_scan" in run for run in runs)
    assert _setup_uv(workflow["jobs"]["upstream-main"])["with"]["enable-cache"] is False


def test_release_workflow_publishes_through_trusted_publishing():
    workflow = _workflow("release.yml")
    job = workflow["jobs"]["publish"]
    assert workflow[True]["push"]["tags"] == ["v*"]
    assert job["permissions"]["id-token"] == "write"
    uses = [step.get("uses", "") for step in job["steps"]]
    assert "pypa/gh-action-pypi-publish@release/v1" in uses
    assert "password" not in (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert job["needs"] == "build"
    assert [use.split("@")[0] for use in uses] == ["actions/download-artifact", "pypa/gh-action-pypi-publish"]
    assert workflow["jobs"]["build"]["permissions"] == {"contents": "read"}  # No id-token in the build job.


def test_release_build_gates_the_upload_on_the_checks_and_the_tag_version():
    build = _workflow("release.yml")["jobs"]["build"]
    runs = [step["run"] for step in build["steps"] if "run" in step]
    assert runs == ["uv sync --locked", "uv run ruff check", "uv run pytest -q", "uv build",
                    'test -f "dist/pr_agent_cli_handlers-${GITHUB_REF_NAME#v}.tar.gz"']
    assert _setup_uv(build)["with"]["enable-cache"] is False
    assert build["steps"][-1]["uses"].startswith("actions/upload-artifact@")
