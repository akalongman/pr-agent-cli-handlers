import os
import sys

import pytest

from pr_agent_cli_handlers.environment import CREDENTIAL_NAME_MARKERS

# Keep LiteLLM from fetching its remote price map when pr_agent is imported, as PR-Agent's own CI does.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


@pytest.fixture(autouse=True)
def _clear_handler_environment(monkeypatch):
    """Remove PR_AGENT_CLI_* and credential-like variables, so the shell can neither change results nor leak secrets.

    A variable counts as credential-like when its upper-cased name contains a CREDENTIAL_NAME_MARKERS entry; a
    test that needs one sets it with monkeypatch.setenv.
    """
    for name in list(os.environ):
        if name.startswith("PR_AGENT_CLI_") or any(marker in name.upper() for marker in CREDENTIAL_NAME_MARKERS):
            monkeypatch.delenv(name)


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    """Put a fake CLI on PATH that records its call, prints canned output and exits.

    The record holds the arguments, stdin, cwd and the content of the ``--system-prompt-file`` file, read while the
    call runs because the handler removes the file afterwards.
    """
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
            "if '--system-prompt-file' in sys.argv:\n"
            "    path = sys.argv[sys.argv.index('--system-prompt-file') + 1]\n"
            "    data['system_prompt'] = open(path, encoding='utf-8').read()\n"
            f"json.dump(data, open({str(record)!r}, 'w'))\n"
            f"sys.stdout.write({stdout!r})\n"
            f"sys.exit({exit_code})\n"
        )
        script.chmod(0o755)
        return record

    return install


@pytest.fixture
def restore_seams():
    """Snapshot the ai_handler defaults activation may replace and the Action runner's key gate cli.main may
    replace, and put them back after the test."""
    import importlib

    from pr_agent_cli_handlers.activation import SEAMS
    from pr_agent_cli_handlers.cli import KEY_GATE

    saved = []
    for seam in SEAMS:
        init = getattr(importlib.import_module(seam.module), seam.qualname).__init__
        saved.append((init, init.__defaults__, init.__kwdefaults__))
    runner = importlib.import_module("pr_agent.servers.github_action_runner")
    gate = getattr(runner, KEY_GATE, None)
    yield
    for init, defaults, kwdefaults in saved:
        init.__defaults__ = defaults
        init.__kwdefaults__ = kwdefaults
    if gate is not None:
        setattr(runner, KEY_GATE, gate)
