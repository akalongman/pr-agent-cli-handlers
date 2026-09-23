import os
import sys

import pytest

# Keep LiteLLM from fetching its remote price map when pr_agent is imported, as PR-Agent's own CI does.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


@pytest.fixture(autouse=True)
def _clear_handler_environment(monkeypatch):
    """Remove PR_AGENT_CLI_* variables so the developer's shell cannot change test results."""
    for name in list(os.environ):
        if name.startswith("PR_AGENT_CLI_"):
            monkeypatch.delenv(name)


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    """Put a fake CLI on PATH that records its arguments, stdin and cwd, prints canned output and exits."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    def install(name, stdout, exit_code=0):
        record = tmp_path / f"{name}.record.json"
        script = bin_dir / name
        script.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "data = {'argv': sys.argv[1:], 'stdin': sys.stdin.read(), 'cwd': os.getcwd()}\n"
            f"json.dump(data, open({str(record)!r}, 'w'))\n"
            f"sys.stdout.write({stdout!r})\n"
            f"sys.exit({exit_code})\n"
        )
        script.chmod(0o755)
        return record

    return install
