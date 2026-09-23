# pr-agent-cli-handlers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `pr-agent-cli-handlers`, an add-on package that runs PR-Agent's commands through the Claude Code, Codex or Antigravity (`agy`) CLI instead of LiteLLM, locally, in GitHub Actions and in GitLab pipelines.

**Architecture:** A shared `CliAIHandler` base (ported from the reviewed fork branch) runs one CLI process per call with settings read from environment variables only, an allowlisted child environment and credential redaction. Three adapters turn prompts into CLI commands and parse the output. An activation module replaces the `ai_handler` default of PR-Agent's eleven handler-taking constructors and then hands over to PR-Agent's own CLI or GitHub Action runner.

**Tech Stack:** Python 3.12+, `pr-agent>=0.46` (PyPI), hatchling, uv, pytest with pytest-asyncio, Ruff, GitHub Actions (composite action), GitLab CI.

**Spec:** `docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md` (requirements R1 to R15, probe results P1 to P6).

## Global Constraints

- Python `>=3.12`. The only runtime dependency is `pr-agent>=0.46`, with no upper bound (R1).
- Distribution `pr-agent-cli-handlers`, import package `pr_agent_cli_handlers` under `src/`, console command `pr-agent-cli-handlers`, MIT license.
- Environment variables, exactly: `PR_AGENT_CLI_HANDLER`, `PR_AGENT_CLI_BINARY`, `PR_AGENT_CLI_EXTRA_ARGS`, `PR_AGENT_CLI_TIMEOUT`, `PR_AGENT_CLI_PASS_ENV` (single underscores; PR-Agent's settings loader turns `SECTION__KEY` variables into settings).
- Handler settings never come from PR-Agent's settings object (R6). The only PR-Agent settings the handlers read are `config.ai_timeout` and `config.reasoning_effort`.
- Model names must match `^[A-Za-z0-9][A-Za-z0-9._:/@-]*$` and keep a non-empty last `/` segment (R7).
- Every handler failure raises `CliHandlerError` (R8). No command-line argument exceeds 120,000 bytes (R11).
- No automated test runs a real `claude`, `codex` or `agy` binary (R15). Live runs happen only through `scripts/smoke`, as named steps in Tasks 6 and 7.
- Ruff rules E, F, B, I at 120 columns; `uv run ruff check` must be clean. Do not run `ruff format`.
- Comments and docstrings are concise and imperative. No em dashes or en dashes anywhere (code, docs, commit messages); hyphens keep their normal use.
- Commits: Conventional Commit titles, signed (commit signing is on; never bypass it), path-limited with `git add <paths> && git commit -m "<title>" -- <paths>`, no trailers, no mention of AI assistants. Never create or switch branches; never push.
- Run tests with `uv run pytest -q` (the test `conftest.py` sets `LITELLM_LOCAL_MODEL_COST_MAP=True`). Local uv is 0.5.9.
- Ported code comes from the fork branch at commit `6c707fe6`: `git -C /home/longman/projects/repositories/The-PR-Agent/pr-agent show 6c707fe6:<path>`.

## Review Focus

1. A model name that is only a provider prefix (`anthropic/`) or starts with `-` (`-rf`, `--claude`) must raise `CliHandlerError`; it must never reach the CLI as an empty or flag-like `--model` value. Pinned in Task 3 (`test_map_model_rejects_names_outside_the_model_pattern`) and Task 4 (`test_map_model_rejects_a_flag_that_contains_claude`).
2. `PR_AGENT_CLI_TIMEOUT` set to `nan`, `inf` or `1e309` must be rejected, never turned into an unbounded wait. Pinned in Task 2 (`test_read_timeout_rejects_values_that_are_not_positive_finite_numbers`).
3. Activation run twice in one process, or with a different handler the second time, must succeed and leave the last handler in place. Pinned in Task 6 (`test_activate_is_repeatable_and_can_switch_handlers`).
4. A required seam whose module fails to import must stop with exit status 2 and a message, not a traceback, and must patch nothing. Pinned in Task 6 (`test_required_seam_import_failure_patches_nothing`).
5. `agy` output with several `result` lines, a non-object result or no result line must use the last object result, or raise `CliHandlerError` when there is none. Pinned in Task 7 (`test_parse_response_uses_the_last_result_line`, `test_parse_response_raises_without_a_result_line`).

---

### Task 1: Project scaffold and CI

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `LICENSE`, `README.md` (stub, replaced in Task 8)
- Create: `src/pr_agent_cli_handlers/__init__.py`, `src/pr_agent_cli_handlers/errors.py`
- Create: `tests/conftest.py`, `tests/test_package.py`
- Create: `.github/workflows/ci.yml`
- Generated: `uv.lock`

**Interfaces:**
- Consumes: nothing.
- Produces: `pr_agent_cli_handlers.__version__ == "0.1.0"`; `pr_agent_cli_handlers.errors.CliHandlerError(RuntimeError)`; the autouse fixture `_clear_handler_environment` in `tests/conftest.py`.

- [ ] **Step 1: Write the packaging files**

`pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "pr-agent-cli-handlers"
dynamic = ["version"]
description = "Run PR-Agent through local agent CLIs (Claude Code, Codex, Antigravity) instead of LiteLLM API calls"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.12"
authors = [{ name = "Avtandil Kikabidze", email = "akalongman@gmail.com" }]
dependencies = ["pr-agent>=0.46"]
classifiers = [
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "License :: OSI Approved :: MIT License",
  "Operating System :: OS Independent",
  "Topic :: Software Development :: Quality Assurance",
]

[project.urls]
Homepage = "https://github.com/akalongman/pr-agent-cli-handlers"
Issues = "https://github.com/akalongman/pr-agent-cli-handlers/issues"

[project.scripts]
pr-agent-cli-handlers = "pr_agent_cli_handlers.cli:entrypoint"

[dependency-groups]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "ruff>=0.6"]

[tool.hatch.version]
path = "src/pr_agent_cli_handlers/__init__.py"

[tool.hatch.build.targets.wheel]
packages = ["src/pr_agent_cli_handlers"]

[tool.ruff]
line-length = 120
src = ["src", "tests"]
lint.select = ["E", "F", "B", "I"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
addopts = "--import-mode=importlib"
```

`.gitignore`:

```
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
dist/
build/
*.egg-info/
.superpowers/
```

`LICENSE`:

```
MIT License

Copyright (c) 2026 Avtandil Kikabidze

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

`README.md` (stub):

```markdown
# pr-agent-cli-handlers

Run PR-Agent through local agent CLIs instead of LiteLLM API calls. Documentation arrives with the first release.
```

- [ ] **Step 2: Write the failing tests**

`tests/conftest.py`:

```python
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
```

`tests/test_package.py`:

```python
from importlib.metadata import version

import pr_agent_cli_handlers
from pr_agent_cli_handlers.errors import CliHandlerError


def test_package_version_matches_the_distribution_metadata():
    assert pr_agent_cli_handlers.__version__ == version("pr-agent-cli-handlers") == "0.1.0"


def test_cli_handler_error_is_a_runtime_error():
    assert issubclass(CliHandlerError, RuntimeError)


def test_pr_agent_dependency_exposes_the_agent_seam():
    from pr_agent.agent.pr_agent import PRAgent

    assert "ai_handler" in PRAgent.__init__.__code__.co_varnames
```

- [ ] **Step 3: Lock, install and watch the tests fail**

Run: `uv lock && uv sync && uv run pytest -q`
Expected: collection fails with `ModuleNotFoundError: No module named 'pr_agent_cli_handlers'` (the package has no modules yet; `uv sync` may also fail to build until Step 4, which is equally a RED result).

- [ ] **Step 4: Write the package modules**

`src/pr_agent_cli_handlers/__init__.py`:

```python
"""Run PR-Agent through local agent CLIs instead of LiteLLM API calls."""

__version__ = "0.1.0"
```

`src/pr_agent_cli_handlers/errors.py`:

```python
"""Define the one exception type every CLI handler failure raises."""


class CliHandlerError(RuntimeError):
    """Signal a failed CLI-backed call; raise it (never swallow it) so retry_with_fallback_models moves on."""
```

- [ ] **Step 5: Run the tests and lint**

Run: `uv sync && uv run pytest -q && uv run ruff check`
Expected: `3 passed`; `All checks passed!`

- [ ] **Step 6: Add the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ["3.12", "3.13"]
    env:
      LITELLM_LOCAL_MODEL_COST_MAP: "True"
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: ${{ matrix.python }}
      - run: uv sync
      - run: uv run ruff check
      - run: uv run pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock .gitignore LICENSE README.md src tests .github && \
  git commit -m "build: scaffold the package, tests and CI" -- pyproject.toml uv.lock .gitignore LICENSE README.md src tests .github
```

---

### Task 2: Environment settings, child environment and redaction

**Files:**
- Create: `src/pr_agent_cli_handlers/environment.py`
- Test: `tests/test_environment.py`

**Interfaces:**
- Consumes: `CliHandlerError` (Task 1).
- Produces, all in `pr_agent_cli_handlers.environment`:
  - constants `HANDLER_VAR`, `BINARY_VAR`, `EXTRA_ARGS_VAR`, `TIMEOUT_VAR`, `PASS_ENV_VAR`, `REDACTED = "[REDACTED]"`, `BASE_ENV_NAMES: frozenset[str]`
  - `read_binary(environ: Mapping[str, str], default: str) -> str`
  - `read_extra_args(environ: Mapping[str, str]) -> list[str]`
  - `read_timeout(environ: Mapping[str, str], fallback: float) -> float`
  - `read_pass_env(environ: Mapping[str, str]) -> list[str]`
  - `build_child_env(environ: Mapping[str, str], adapter_names: Iterable[str], pass_names: Iterable[str]) -> dict[str, str]`
  - `credential_values(environ: Mapping[str, str], credential_names: Iterable[str]) -> list[str]` (longest first)
  - `redact(text: str, secrets: Iterable[str]) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_environment.py`:

```python
import pytest

from pr_agent_cli_handlers.environment import (
    BINARY_VAR,
    EXTRA_ARGS_VAR,
    PASS_ENV_VAR,
    REDACTED,
    TIMEOUT_VAR,
    build_child_env,
    credential_values,
    read_binary,
    read_extra_args,
    read_pass_env,
    read_timeout,
    redact,
)
from pr_agent_cli_handlers.errors import CliHandlerError

PARENT = {
    "PATH": "/usr/bin",
    "HOME": "/home/u",
    "LC_ALL": "C.UTF-8",
    "HTTPS_PROXY": "http://proxy:3128",
    "GITHUB_TOKEN": "ghs_sentinel_github",
    "GITLAB__PERSONAL_ACCESS_TOKEN": "glpat-sentinel-gitlab",
    "CI_JOB_TOKEN": "sentinel-ci-job",
    "OPENAI_API_KEY": "sk-sentinel-openai",
    "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-sentinel",
    "EXTRA_ONE": "extra-value",
    "UNRELATED": "x",
}


def test_read_binary_uses_the_variable_or_the_default():
    assert read_binary({}, "claude") == "claude"
    assert read_binary({BINARY_VAR: "  "}, "claude") == "claude"
    assert read_binary({BINARY_VAR: "/opt/bin/claude"}, "claude") == "/opt/bin/claude"


def test_read_extra_args_shell_splits_the_variable():
    assert read_extra_args({}) == []
    assert read_extra_args({EXTRA_ARGS_VAR: "--verbose --foo 'a b'"}) == ["--verbose", "--foo", "a b"]


def test_read_extra_args_names_the_variable_when_it_cannot_be_split():
    with pytest.raises(CliHandlerError, match=EXTRA_ARGS_VAR):
        read_extra_args({EXTRA_ARGS_VAR: "--foo 'unbalanced"})


def test_read_timeout_falls_back_when_unset_or_blank():
    assert read_timeout({}, 120) == 120.0
    assert read_timeout({TIMEOUT_VAR: " "}, 120) == 120.0
    assert read_timeout({TIMEOUT_VAR: "2.5"}, 120) == 2.5


@pytest.mark.parametrize("raw", ["0", "-1", "abc", "nan", "inf", "-inf", "1e309"])
def test_read_timeout_rejects_values_that_are_not_positive_finite_numbers(raw):
    with pytest.raises(CliHandlerError, match=TIMEOUT_VAR):
        read_timeout({TIMEOUT_VAR: raw}, 120)


def test_read_pass_env_trims_names_and_skips_empty_entries():
    assert read_pass_env({}) == []
    assert read_pass_env({PASS_ENV_VAR: " EXTRA_ONE, ,EXTRA_TWO,"}) == ["EXTRA_ONE", "EXTRA_TWO"]


@pytest.mark.parametrize("raw", ["EXTRA-ONE", "A B", "PATH;rm"])
def test_read_pass_env_rejects_invalid_names(raw):
    with pytest.raises(CliHandlerError, match=PASS_ENV_VAR):
        read_pass_env({PASS_ENV_VAR: raw})


def test_build_child_env_keeps_base_adapter_and_passed_names_only():
    env = build_child_env(PARENT, {"CLAUDE_CODE_OAUTH_TOKEN"}, ["EXTRA_ONE"])

    assert env == {
        "PATH": "/usr/bin",
        "HOME": "/home/u",
        "LC_ALL": "C.UTF-8",
        "HTTPS_PROXY": "http://proxy:3128",
        "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-sentinel",
        "EXTRA_ONE": "extra-value",
    }


def test_credential_values_cover_adapter_names_and_credential_like_names_of_useful_length():
    parent = {**PARENT, "SHORT_TOKEN": "abc", "my_api_key": "lowercase-key-value"}

    values = credential_values(parent, {"EXTRA_ONE"})

    assert set(values) == {
        "ghs_sentinel_github", "glpat-sentinel-gitlab", "sentinel-ci-job", "sk-sentinel-openai",
        "sk-ant-oat-sentinel", "lowercase-key-value", "extra-value",
    }
    assert values == sorted(values, key=len, reverse=True)


def test_redact_replaces_every_occurrence_and_prefers_the_longest_secret():
    text = "a sk-ant-oat-sentinel b sk-ant-oat-sentinel-long c sk-ant-oat-sentinel"

    assert redact(text, ["sk-ant-oat-sentinel", "sk-ant-oat-sentinel-long"]) == (
        f"a {REDACTED} b {REDACTED} c {REDACTED}")
    assert redact("nothing here", ["sk-ant-oat-sentinel"]) == "nothing here"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_environment.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pr_agent_cli_handlers.environment'`

- [ ] **Step 3: Write the module**

`src/pr_agent_cli_handlers/environment.py`:

```python
"""Read handler settings from the process environment, build the CLI's environment, and redact credentials.

Keep handler settings in the environment rather than in PR-Agent's settings object: PR-Agent merges a
repository's .pr_agent.toml into its settings, and that file has no path into the process environment.
"""
import math
import re
import shlex
from typing import Iterable, Mapping

from pr_agent_cli_handlers.errors import CliHandlerError

HANDLER_VAR = "PR_AGENT_CLI_HANDLER"
BINARY_VAR = "PR_AGENT_CLI_BINARY"
EXTRA_ARGS_VAR = "PR_AGENT_CLI_EXTRA_ARGS"
TIMEOUT_VAR = "PR_AGENT_CLI_TIMEOUT"
PASS_ENV_VAR = "PR_AGENT_CLI_PASS_ENV"

# Pass these to every CLI: process basics, locale, temporary and XDG directories, proxies and CA bundles.
BASE_ENV_NAMES = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LANGUAGE", "TZ", "TMPDIR", "TEMP", "TMP",
    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "no_proxy", "all_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
})
BASE_ENV_PREFIXES = ("LC_",)
CREDENTIAL_NAME_MARKERS = ("TOKEN", "KEY", "SECRET", "PASSWORD")
MIN_SECRET_LENGTH = 8
REDACTED = "[REDACTED]"
_ENV_NAME = re.compile(r"[A-Za-z0-9_]+")


def read_binary(environ: Mapping[str, str], default: str) -> str:
    """Return PR_AGENT_CLI_BINARY, or ``default`` when it is unset or blank."""
    return environ.get(BINARY_VAR, "").strip() or default


def read_extra_args(environ: Mapping[str, str]) -> list[str]:
    """Return PR_AGENT_CLI_EXTRA_ARGS split the way a POSIX shell splits words."""
    raw = environ.get(EXTRA_ARGS_VAR, "")
    try:
        return shlex.split(raw)
    except ValueError as e:
        raise CliHandlerError(f"cannot parse {EXTRA_ARGS_VAR}: {e}") from e


def read_timeout(environ: Mapping[str, str], fallback: float) -> float:
    """Return PR_AGENT_CLI_TIMEOUT in seconds, or ``fallback`` when it is unset or blank."""
    raw = environ.get(TIMEOUT_VAR, "").strip()
    if not raw:
        return float(fallback)
    try:
        value = float(raw)
    except ValueError as e:
        raise CliHandlerError(f"{TIMEOUT_VAR} must be a positive number of seconds, got {raw!r}") from e
    if not math.isfinite(value) or value <= 0:
        raise CliHandlerError(f"{TIMEOUT_VAR} must be a positive number of seconds, got {raw!r}")
    return value


def read_pass_env(environ: Mapping[str, str]) -> list[str]:
    """Return the variable names listed in PR_AGENT_CLI_PASS_ENV, trimmed, without empty entries."""
    names = []
    for entry in environ.get(PASS_ENV_VAR, "").split(","):
        name = entry.strip()
        if not name:
            continue
        if not _ENV_NAME.fullmatch(name):
            raise CliHandlerError(f"{PASS_ENV_VAR} contains an invalid variable name: {name!r}")
        names.append(name)
    return names


def build_child_env(environ: Mapping[str, str], adapter_names: Iterable[str],
                    pass_names: Iterable[str]) -> dict[str, str]:
    """Return the subset of ``environ`` a CLI may see: base names, the adapter's names and the passed names."""
    allowed = BASE_ENV_NAMES | frozenset(adapter_names) | frozenset(pass_names)
    return {name: value for name, value in environ.items()
            if name in allowed or name.startswith(BASE_ENV_PREFIXES)}


def credential_values(environ: Mapping[str, str], credential_names: Iterable[str]) -> list[str]:
    """Return credential values worth redacting, longest first.

    Include the adapter's credential variables and every variable whose name contains TOKEN, KEY, SECRET or
    PASSWORD in any case, skipping values shorter than MIN_SECRET_LENGTH so short flags such as "1" survive.
    """
    names = frozenset(credential_names)
    values = {
        value for name, value in environ.items()
        if len(value) >= MIN_SECRET_LENGTH
        and (name in names or any(marker in name.upper() for marker in CREDENTIAL_NAME_MARKERS))
    }
    return sorted(values, key=len, reverse=True)


def redact(text: str, secrets: Iterable[str]) -> str:
    """Replace every occurrence of each secret in ``text`` with REDACTED, longest secret first."""
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret and secret in text:
            text = text.replace(secret, REDACTED)
    return text
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_environment.py -q && uv run ruff check`
Expected: all `test_environment.py` tests pass; `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/pr_agent_cli_handlers/environment.py tests/test_environment.py && \
  git commit -m "feat: read handler settings from the environment and redact credentials" -- \
  src/pr_agent_cli_handlers/environment.py tests/test_environment.py
```

---

### Task 3: Shared CLI handler base

**Files:**
- Create: `src/pr_agent_cli_handlers/base.py`
- Test: `tests/test_base.py` (ported from the branch's `tests/unittest/test_cli_ai_handler.py`, then extended)

**Interfaces:**
- Consumes: Task 2's `read_binary`, `read_extra_args`, `read_timeout`, `read_pass_env`, `build_child_env`, `credential_values`, `redact`; Task 1's `CliHandlerError`.
- Produces, in `pr_agent_cli_handlers.base`:
  - `MAX_ARGV_ELEMENT_BYTES = 120_000`, `MODEL_NAME` (compiled pattern)
  - `@dataclass CliCommand(argv: list[str], stdin: Optional[str] = None, cwd: Optional[str] = None)`
  - `@dataclass CliResponse(text: str, finish_reason: str = "stop", prompt_tokens: int = 0, completion_tokens: int = 0, cost_usd: Optional[float] = None)`
  - `class CliAIHandler(BaseAiHandler)` with class attributes `default_binary: str`, `supports_images: bool`, `credential_env: frozenset[str]`, `config_env: frozenset[str]`; instance attributes `binary`, `extra_args`, `timeout`, `pass_env`; abstract `build_command(model, system, user) -> CliCommand` and `parse_response(stdout) -> CliResponse`; `map_model(model) -> str`; static `reasoning_effort() -> str`; `create_workdir(prefix: str) -> str`; `child_env() -> dict[str, str]`; `credential_values() -> list[str]`; `async chat_completion(model, system, user, temperature=0.2, img_path=None) -> tuple[str, str]`; `async _run(command: CliCommand) -> str`.

- [ ] **Step 1: Port the test file**

Run: `git -C /home/longman/projects/repositories/The-PR-Agent/pr-agent show 6c707fe6:tests/unittest/test_cli_ai_handler.py > tests/test_base.py`

Then apply these edits to `tests/test_base.py`:

1. Replace the import block

```python
import pr_agent.algo.ai_handlers.cli_ai_handler as cli_module
from pr_agent.algo.ai_handlers.cli_ai_handler import (
    MAX_ARGV_ELEMENT_BYTES,
    CliAIHandler,
    CliCommand,
    CliHandlerError,
    CliResponse,
)
from pr_agent.algo.run_details import get_run_details, init_run_details
```

with

```python
from pr_agent.algo.run_details import get_run_details, init_run_details

import pr_agent_cli_handlers.base as cli_module
from pr_agent_cli_handlers.base import MAX_ARGV_ELEMENT_BYTES, CliAIHandler, CliCommand, CliResponse
from pr_agent_cli_handlers.errors import CliHandlerError
```

and add `import gc` and `import json` to the standard-library imports at the top.

2. In `class _EchoAdapter`, replace

```python
    settings_section = "echo"
    default_binary = "echo-bin"
```

with

```python
    default_binary = "echo-bin"
    credential_env = frozenset({"ECHO_API_KEY"})
```

3. Delete these four tests (including the `@pytest.mark.parametrize` decorator of the second): `test_settings_section_supplies_binary_extra_args_and_timeout`, `test_extra_args_that_is_neither_a_list_nor_a_string_raises_naming_the_setting`, `test_extra_args_as_string_is_shell_split_into_the_built_command`, `test_unparseable_extra_args_string_raises_naming_the_setting`. Insert in their place:

```python
def test_environment_supplies_binary_extra_args_and_timeout(monkeypatch):
    _install_settings(monkeypatch)
    monkeypatch.setenv("PR_AGENT_CLI_BINARY", "/opt/echo")
    monkeypatch.setenv("PR_AGENT_CLI_EXTRA_ARGS", "--x 1")
    monkeypatch.setenv("PR_AGENT_CLI_TIMEOUT", "5")
    handler = _EchoAdapter()
    assert handler.binary == "/opt/echo"
    assert handler.extra_args == ["--x", "1"]
    assert handler.timeout == 5.0
    assert handler.deployment_id is None


def test_extra_args_are_shell_split_into_the_built_command(monkeypatch):
    _install_settings(monkeypatch)
    monkeypatch.setenv("PR_AGENT_CLI_EXTRA_ARGS", "--verbose --foo 'a b'")
    handler = _EchoAdapter()

    assert handler.extra_args == ["--verbose", "--foo", "a b"]
    assert handler.build_command("m", "sys", "usr").argv[-3:] == ["--verbose", "--foo", "a b"]


def test_unparseable_extra_args_raise_naming_the_variable(monkeypatch):
    _install_settings(monkeypatch)
    monkeypatch.setenv("PR_AGENT_CLI_EXTRA_ARGS", "--foo 'unbalanced")

    with pytest.raises(CliHandlerError, match="PR_AGENT_CLI_EXTRA_ARGS"):
        _EchoAdapter()
```

4. In `test_run_raises_on_timeout`, replace `_install_settings(monkeypatch, {"ECHO.TIMEOUT": 0.2})` with:

```python
    _install_settings(monkeypatch)
    monkeypatch.setenv("PR_AGENT_CLI_TIMEOUT", "0.2")
```

5. In `test_run_kills_process_tree_on_timeout`, replace `_install_settings(monkeypatch, {"ECHO.TIMEOUT": 0.3})` with:

```python
    _install_settings(monkeypatch)
    monkeypatch.setenv("PR_AGENT_CLI_TIMEOUT", "0.3")
```

6. Append these tests at the end of the file:

```python
@pytest.mark.parametrize("model", ["-rf", "--dangerously-skip-permissions", "a b", "claude;rm", "", "anthropic/",
                                   "x\n", "/claude"])
def test_map_model_rejects_names_outside_the_model_pattern(monkeypatch, model):
    _install_settings(monkeypatch)
    with pytest.raises(CliHandlerError, match="invalid model name"):
        _EchoAdapter().map_model(model)


@pytest.mark.parametrize("model, expected", [
    ("openrouter/anthropic/claude-x", "claude-x"),
    ("vertex_ai/claude-opus-4@20250514", "claude-opus-4@20250514"),
    ("gpt-6-astra", "gpt-6-astra"),
])
def test_map_model_keeps_the_last_segment_of_a_valid_name(monkeypatch, model, expected):
    _install_settings(monkeypatch)
    assert _EchoAdapter().map_model(model) == expected


async def test_run_passes_only_the_allowlisted_environment(monkeypatch):
    _install_settings(monkeypatch)
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_sentinel_github")
    monkeypatch.setenv("GITLAB__PERSONAL_ACCESS_TOKEN", "glpat-sentinel-gitlab")
    monkeypatch.setenv("CI_JOB_TOKEN", "sentinel-ci-job")
    monkeypatch.setenv("ECHO_API_KEY", "echo-api-key-value")
    monkeypatch.setenv("EXTRA_ONE", "extra-value")
    monkeypatch.setenv("PR_AGENT_CLI_PASS_ENV", "EXTRA_ONE")
    handler = _RealProcessAdapter()
    command = CliCommand(argv=[sys.executable, "-c", "import json, os; print(json.dumps(sorted(os.environ)))"])

    names = set(json.loads(await handler._run(command)))

    assert not names & {"GITHUB_TOKEN", "GITLAB__PERSONAL_ACCESS_TOKEN", "CI_JOB_TOKEN"}
    assert {"PATH", "ECHO_API_KEY", "EXTRA_ONE"} <= names


async def test_run_redacts_credential_values_from_output_and_errors(monkeypatch):
    _install_settings(monkeypatch)
    monkeypatch.setenv("ECHO_API_KEY", "echo-api-key-value")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_sentinel_github")
    handler = _RealProcessAdapter()
    leak = "print('key=echo-api-key-value gh=ghs_sentinel_github')"

    output = await handler._run(CliCommand(argv=[sys.executable, "-c", leak]))

    assert output.strip() == "key=[REDACTED] gh=[REDACTED]"
    failing = "import sys; sys.stderr.write('echo-api-key-value'); sys.exit(1)"
    with pytest.raises(CliHandlerError) as exc_info:
        await handler._run(CliCommand(argv=[sys.executable, "-c", failing]))
    assert "echo-api-key-value" not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


async def test_run_starts_the_command_in_its_working_directory(monkeypatch, tmp_path):
    _install_settings(monkeypatch)
    handler = _RealProcessAdapter()
    command = CliCommand(argv=[sys.executable, "-c", "import os; print(os.getcwd())"], cwd=str(tmp_path))

    assert os.path.realpath((await handler._run(command)).strip()) == os.path.realpath(tmp_path)


def test_create_workdir_is_removed_when_the_handler_is_garbage_collected(monkeypatch):
    _install_settings(monkeypatch)
    handler = _EchoAdapter()
    workdir = handler.create_workdir("pr-agent-test-")
    assert os.path.isdir(workdir)

    del handler
    gc.collect()

    assert not os.path.exists(workdir)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_base.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pr_agent_cli_handlers.base'`

- [ ] **Step 3: Write the base module**

`src/pr_agent_cli_handlers/base.py`:

```python
"""Share the subprocess plumbing of AI handlers that run a local command-line agent once per call.

An adapter subclass decides how a prompt becomes a command (argv, stdin and working directory) and how
the command's stdout becomes text and token counts. This base owns the settings read from the
environment, the subprocess and its allowlisted environment, the timeout, failure mapping, credential
redaction, logging and run-details accounting.
"""
import asyncio
import os
import re
import shutil
import signal
import tempfile
import weakref
from abc import abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from typing import Optional

from pr_agent.algo.ai_handlers.base_ai_handler import BaseAiHandler
from pr_agent.algo.run_details import record_ai_call
from pr_agent.config_loader import get_settings
from pr_agent.log import get_logger

from pr_agent_cli_handlers.environment import (
    build_child_env,
    credential_values,
    read_binary,
    read_extra_args,
    read_pass_env,
    read_timeout,
    redact,
)
from pr_agent_cli_handlers.errors import CliHandlerError

# Linux rejects a single argv element above 128 KiB (MAX_ARG_STRLEN); keep a margin below it.
MAX_ARGV_ELEMENT_BYTES = 120_000
# Accept only plain model identifiers: a repository's .pr_agent.toml can set config.model.
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]*")


@dataclass
class CliCommand:
    argv: list[str]
    stdin: Optional[str] = None
    cwd: Optional[str] = None


@dataclass
class CliResponse:
    text: str
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Optional[float] = None


class CliAIHandler(BaseAiHandler):
    default_binary: str = ""
    supports_images: bool = False
    # Pass these secret variables to the CLI for its own authentication, and redact their values from its output.
    credential_env: frozenset[str] = frozenset()
    # Pass these non-secret variables (regions, endpoints, provider switches) to the CLI.
    config_env: frozenset[str] = frozenset()

    def __init__(self):
        super().__init__()
        self.binary = read_binary(os.environ, self.default_binary)
        self.extra_args = read_extra_args(os.environ)
        self.timeout = read_timeout(os.environ, float(get_settings().config.ai_timeout))
        self.pass_env = read_pass_env(os.environ)

    @property
    def deployment_id(self):
        return None

    @abstractmethod
    def build_command(self, model: str, system: str, user: str) -> CliCommand:
        """Return the full argv (binary first), the text to feed on stdin, and the working directory."""

    @abstractmethod
    def parse_response(self, stdout: str) -> CliResponse:
        """Turn the command's stdout into text and counts; raise CliHandlerError on a reported failure."""

    def map_model(self, model: str) -> str:
        """Validate ``model`` and return its last ``/``-separated segment; adapters may narrow this.

        Drop every provider prefix, so ``openrouter/anthropic/claude-x`` becomes ``claude-x``.
        """
        if isinstance(model, str) and MODEL_NAME.fullmatch(model):
            name = model.rsplit("/", 1)[-1]
            if name:
                return name
        raise CliHandlerError(f"{type(self).__name__}: invalid model name {model!r}")

    @staticmethod
    def reasoning_effort() -> str:
        """Return ``config.reasoning_effort`` lower-cased, or an empty string when it is unset."""
        return str(get_settings().get("CONFIG.REASONING_EFFORT", "") or "").lower()

    def create_workdir(self, prefix: str) -> str:
        """Create an empty directory for this handler's lifetime and remove it when the handler is collected.

        Use one directory per handler instance, not per call: parallel calls on the same instance (for example
        PRCodeSuggestions' asyncio.gather) share it instead of racing to create their own. Remove it with
        weakref.finalize, since a chat_completion adapter has no synchronous "close" hook.
        """
        workdir = tempfile.mkdtemp(prefix=prefix)
        weakref.finalize(self, shutil.rmtree, workdir, ignore_errors=True)
        return workdir

    def child_env(self) -> dict[str, str]:
        """Return the environment the CLI receives: base names, this adapter's names, PR_AGENT_CLI_PASS_ENV."""
        return build_child_env(os.environ, self.credential_env | self.config_env, self.pass_env)

    def credential_values(self) -> list[str]:
        """Return the credential values to redact from anything the CLI prints."""
        return credential_values(os.environ, self.credential_env)

    async def chat_completion(self, model: str, system: str, user: str, temperature: float = 0.2, img_path: str = None):
        if img_path and not self.supports_images:
            get_logger().warning(
                f"Image path is not supported for {type(self).__name__}. Ignoring image path: {img_path}")
        mapped_model = self.map_model(model)
        command = self.build_command(mapped_model, system, user)
        for arg in command.argv:
            if len(arg.encode("utf-8")) > MAX_ARGV_ELEMENT_BYTES:
                raise CliHandlerError(
                    f"{type(self).__name__}: a command argument exceeds {MAX_ARGV_ELEMENT_BYTES} bytes; "
                    "the prompt does not fit in one argv element")
        get_logger().debug("Prompts", artifact={"system": system, "user": user})
        stdout = await self._run(command)
        try:
            response = self.parse_response(stdout)
        except CliHandlerError:
            raise
        except Exception as e:
            raise CliHandlerError(
                f"{type(self).__name__}: cannot parse the output of {command.argv[0]}: {type(e).__name__}: {e}") from e
        get_logger().info("AI response", response=response.text, finish_reason=response.finish_reason,
                          model=mapped_model, prompt_tokens=response.prompt_tokens,
                          completion_tokens=response.completion_tokens)
        usage = {
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.prompt_tokens + response.completion_tokens,
        }
        record_ai_call(usage, model=mapped_model, cost_usd=response.cost_usd)
        return response.text, response.finish_reason

    async def _run(self, command: CliCommand) -> str:
        stdin_pipe = asyncio.subprocess.PIPE if command.stdin is not None else asyncio.subprocess.DEVNULL
        try:
            process = await asyncio.create_subprocess_exec(
                *command.argv, stdin=stdin_pipe, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=command.cwd, env=self.child_env(), start_new_session=(os.name == "posix"))
        except FileNotFoundError as e:
            raise CliHandlerError(f"{type(self).__name__}: command not found: {command.argv[0]}") from e
        except (OSError, ValueError) as e:
            # Report every other launch failure as a CliHandlerError too, so every CLI failure reaches
            # callers as one exception type: an OSError (PermissionError, E2BIG "Argument list too long")
            # or the ValueError subprocess raises for an argument that contains a NUL byte.
            raise CliHandlerError(f"{type(self).__name__}: cannot run {command.argv[0]}: {e}") from e
        payload = command.stdin.encode("utf-8") if command.stdin is not None else None
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(payload), timeout=self.timeout)
        except asyncio.TimeoutError as e:
            await self._kill_process_tree(process)
            raise CliHandlerError(f"{type(self).__name__}: {command.argv[0]} timed out after {self.timeout:g}s") from e
        except asyncio.CancelledError:
            await self._kill_process_tree(process)
            raise
        secrets = self.credential_values()
        if process.returncode != 0:
            detail_parts = []
            for label, stream in (("stderr", stderr), ("stdout", stdout)):
                stream_tail = stream.decode("utf-8", errors="replace")[-2000:]
                if stream_tail:
                    detail_parts.append(f"{label}: {stream_tail}")
            detail = redact("; ".join(detail_parts), secrets)
            raise CliHandlerError(
                f"{type(self).__name__}: {command.argv[0]} exited with {process.returncode}: {detail}")
        return redact(stdout.decode("utf-8", errors="replace"), secrets)

    @staticmethod
    async def _kill_process_tree(process: asyncio.subprocess.Process) -> None:
        """Kill every process the CLI spawned, not just the direct child, then reap it.

        A grandchild that inherited the pipes keeps them open after the direct child dies,
        so ``process.wait()`` would otherwise block until that grandchild exits on its own
        (Python resolves it only once the pipes close). Killing the whole process group
        avoids that: the child was started as its own session leader, so its pid doubles as
        the process group id.
        """
        if os.name == "posix":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        else:
            with suppress(ProcessLookupError):
                process.kill()
        await process.wait()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run ruff check --fix tests/test_base.py && uv run pytest tests/test_base.py -q && uv run ruff check`
Expected: all `test_base.py` tests pass; `All checks passed!` (`--fix` only sorts the edited imports).

- [ ] **Step 5: Commit**

```bash
git add src/pr_agent_cli_handlers/base.py tests/test_base.py && \
  git commit -m "feat: add the shared CLI handler base with an allowlisted environment" -- \
  src/pr_agent_cli_handlers/base.py tests/test_base.py
```

---

### Task 4: Claude Code adapter

**Files:**
- Create: `src/pr_agent_cli_handlers/claude_code.py`
- Modify: `tests/conftest.py` (add the `fake_cli` fixture)
- Test: `tests/test_claude_code.py` (ported from the branch's `tests/unittest/test_claude_code_ai_handler.py`, then extended)

**Interfaces:**
- Consumes: Task 3's `CliAIHandler`, `CliCommand`, `CliResponse`; `CliHandlerError`.
- Produces: `pr_agent_cli_handlers.claude_code.ClaudeCodeAIHandler` (`default_binary = "claude"`), constants `CLAUDE_CODE_EFFORTS`, `CLAUDE_ALIASES`; the `fake_cli(name: str, stdout: str, exit_code: int = 0) -> pathlib.Path` fixture, which returns the path of a JSON record `{"argv": [...], "stdin": "...", "cwd": "..."}` written by the fake binary.

- [ ] **Step 1: Add the `fake_cli` fixture**

Add `import sys` to the imports of `tests/conftest.py` and append:

```python
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
```

- [ ] **Step 2: Port the test file**

Run: `git -C /home/longman/projects/repositories/The-PR-Agent/pr-agent show 6c707fe6:tests/unittest/test_claude_code_ai_handler.py > tests/test_claude_code.py`

Then apply these edits to `tests/test_claude_code.py`:

1. Replace the three `pr_agent.algo.ai_handlers` imports with:

```python
import pr_agent_cli_handlers.base as cli_module
from pr_agent_cli_handlers.claude_code import ClaudeCodeAIHandler
from pr_agent_cli_handlers.errors import CliHandlerError
```

2. In `test_build_command_uses_the_restricted_headless_flag_set`, replace
`_install_settings(monkeypatch, {"CONFIG.REASONING_EFFORT": "xhigh", "CLAUDE_CODE.EXTRA_ARGS": ["--verbose"]})` with:

```python
    _install_settings(monkeypatch, {"CONFIG.REASONING_EFFORT": "xhigh"})
    monkeypatch.setenv("PR_AGENT_CLI_EXTRA_ARGS", "--verbose")
```

3. Append:

```python
def test_claude_code_names_its_credential_and_config_variables():
    assert ClaudeCodeAIHandler.credential_env == {
        "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    }
    assert ClaudeCodeAIHandler.config_env == {
        "ANTHROPIC_BASE_URL", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
        "ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION", "GOOGLE_APPLICATION_CREDENTIALS", "AWS_REGION",
        "AWS_PROFILE",
    }


def test_child_env_keeps_the_subscription_token_and_drops_other_tokens(monkeypatch):
    _install_settings(monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-sentinel")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-sentinel-openai")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_sentinel_github")

    env = ClaudeCodeAIHandler().child_env()

    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat-sentinel"
    assert "OPENAI_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env


def test_map_model_rejects_a_flag_that_contains_claude(monkeypatch):
    _install_settings(monkeypatch)
    with pytest.raises(CliHandlerError, match="invalid model name"):
        ClaudeCodeAIHandler().map_model("--claude")


async def test_contract_runs_the_claude_binary_with_the_built_command(monkeypatch, fake_cli):
    _install_settings(monkeypatch)
    record = fake_cli("claude", _success_payload(result="looks good"))
    handler = ClaudeCodeAIHandler()

    text, finish_reason = await handler.chat_completion(model="anthropic/claude-opus-5", system="SYS", user="USER")

    recorded = json.loads(record.read_text())
    assert (text, finish_reason) == ("looks good", "stop")
    assert recorded["argv"] == handler.build_command("claude-opus-5", "SYS", "USER").argv[1:]
    assert recorded["stdin"] == "USER"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_claude_code.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pr_agent_cli_handlers.claude_code'`

- [ ] **Step 4: Write the adapter**

`src/pr_agent_cli_handlers/claude_code.py`:

```python
"""Run Claude Code headless (``claude -p``) once per call.

The flag set turns the harness into a plain completion: its own system prompt is replaced,
tools, settings files and MCP servers are off, and nothing is persisted. Authentication is
the harness's own login; this adapter reads no credentials.
"""
import json

from pr_agent_cli_handlers.base import CliAIHandler, CliCommand, CliResponse
from pr_agent_cli_handlers.errors import CliHandlerError

CLAUDE_CODE_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
CLAUDE_ALIASES = frozenset({"opus", "sonnet", "haiku", "fable"})


class ClaudeCodeAIHandler(CliAIHandler):
    default_binary = "claude"
    credential_env = frozenset({
        "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    })
    config_env = frozenset({
        "ANTHROPIC_BASE_URL", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
        "ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION", "GOOGLE_APPLICATION_CREDENTIALS", "AWS_REGION",
        "AWS_PROFILE",
    })

    def map_model(self, model: str) -> str:
        name = super().map_model(model)
        if name.startswith("anthropic."):
            name = name[len("anthropic."):]
        if "claude" not in name and name not in CLAUDE_ALIASES:
            raise CliHandlerError(f"ClaudeCodeAIHandler supports Claude models only, got '{model}'")
        return name

    def build_command(self, model: str, system: str, user: str) -> CliCommand:
        argv = [
            self.binary, "-p",
            "--restricted", "--strict-mcp-config", "--tools", "",
            "--no-session-persistence", "--output-format", "json",
            "--system-prompt", system, "--model", model,
        ]
        effort = self.reasoning_effort()
        if effort in CLAUDE_CODE_EFFORTS:
            argv += ["--effort", effort]
        argv += self.extra_args
        return CliCommand(argv=argv, stdin=user)

    def parse_response(self, stdout: str) -> CliResponse:
        try:
            data = json.loads(stdout)
        except ValueError as e:
            raise CliHandlerError("Claude Code did not return a JSON result") from e
        if not isinstance(data, dict):
            raise CliHandlerError(f"Claude Code reported an error: {stdout[:500]}")
        if data.get("is_error") or data.get("subtype") != "success":
            message = "Claude Code reported an error"
            subtype = data.get("subtype")
            # Name the subtype only when it says more than "success", which an is_error result can still carry.
            if subtype and subtype != "success":
                message += f" ({subtype})"
            if data.get("result"):
                message += f": {str(data['result'])[:500]}"
            raise CliHandlerError(message)
        usage = data.get("usage") or {}
        prompt_tokens = sum(int(usage.get(key) or 0)
                            for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        completion_tokens = int(usage.get("output_tokens") or 0)
        finish_reason = "length" if data.get("stop_reason") == "max_tokens" else "stop"
        cost = data.get("total_cost_usd")
        return CliResponse(text=data.get("result") or "", finish_reason=finish_reason,
                           prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                           cost_usd=float(cost) if cost else None)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run ruff check --fix tests/test_claude_code.py && uv run pytest -q && uv run ruff check`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/pr_agent_cli_handlers/claude_code.py tests/test_claude_code.py tests/conftest.py && \
  git commit -m "feat: add the Claude Code adapter" -- \
  src/pr_agent_cli_handlers/claude_code.py tests/test_claude_code.py tests/conftest.py
```

---

### Task 5: Codex adapter

**Files:**
- Create: `src/pr_agent_cli_handlers/codex.py`
- Test: `tests/test_codex.py` (ported from the branch's `tests/unittest/test_codex_ai_handler.py`, then extended)

**Interfaces:**
- Consumes: Task 3's base; Task 4's `fake_cli` fixture.
- Produces: `pr_agent_cli_handlers.codex.CodexAIHandler` (`default_binary = "codex"`, attribute `workdir`), `toml_basic_string(text: str) -> str`, constants `CODEX_EFFORTS`, `CODEX_EFFORT_ALIASES`, `CODEX_DISABLED_FEATURES`.

- [ ] **Step 1: Port the test file**

Run: `git -C /home/longman/projects/repositories/The-PR-Agent/pr-agent show 6c707fe6:tests/unittest/test_codex_ai_handler.py > tests/test_codex.py`

Then apply these edits to `tests/test_codex.py`:

1. Replace the three `pr_agent.algo.ai_handlers` imports with:

```python
import pr_agent_cli_handlers.base as cli_module
from pr_agent_cli_handlers.codex import CodexAIHandler, toml_basic_string
from pr_agent_cli_handlers.errors import CliHandlerError
```

2. Replace the whole `test_build_command_places_global_flags_before_exec` function with:

```python
def test_build_command_places_global_flags_before_exec(monkeypatch):
    _install_settings(monkeypatch, {"CONFIG.REASONING_EFFORT": "max"})
    monkeypatch.setenv("PR_AGENT_CLI_EXTRA_ARGS", "--profile ci")
    handler = CodexAIHandler()
    command = handler.build_command("gpt-5.6", "SYS line1\nline2", "USER")

    assert command.argv == [
        "codex", "--ask-for-approval", "never", "--sandbox", "read-only", "--model", "gpt-5.6",
        "--config", "features.shell_tool=false",
        "--config", "features.unified_exec=false",
        "--config", "features.browser_use=false",
        "--config", "features.computer_use=false",
        "--config", "features.apps=false",
        "--config", "features.plugins=false",
        "--config", "features.view_image=false",
        "--config", "features.image_generation=false",
        "--config", "features.in_app_browser=false",
        "--config", 'developer_instructions="SYS line1\\nline2"',
        "--config", 'model_reasoning_effort="max"',
        "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
        "--color", "never", "--cd", handler.workdir, "--profile", "ci", "-",
    ]
    assert command.stdin == "USER"
```

3. Append:

```python
def test_codex_names_its_credential_and_config_variables():
    assert CodexAIHandler.credential_env == {"OPENAI_API_KEY", "CODEX_API_KEY"}
    assert CodexAIHandler.config_env == {"OPENAI_BASE_URL", "CODEX_HOME"}


async def test_contract_runs_the_codex_binary_with_the_built_command(monkeypatch, fake_cli):
    _install_settings(monkeypatch)
    record = fake_cli("codex", _events(
        {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": "looks good"}},
        {"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 3}},
    ))
    handler = CodexAIHandler()

    text, finish_reason = await handler.chat_completion(model="openai/gpt-6-astra", system="SYS", user="USER")

    recorded = json.loads(record.read_text())
    assert (text, finish_reason) == ("looks good", "stop")
    assert recorded["argv"] == handler.build_command("gpt-6-astra", "SYS", "USER").argv[1:]
    assert recorded["stdin"] == "USER"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_codex.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pr_agent_cli_handlers.codex'`

- [ ] **Step 3: Write the adapter**

`src/pr_agent_cli_handlers/codex.py`:

```python
"""Run the OpenAI Codex CLI non-interactively (``codex exec``) once per call.

Global flags go before the subcommand: approvals off, a read-only sandbox, the model, every tool
feature switched off so the run is a plain completion, and PR-Agent's system prompt as
``developer_instructions``. The run is ephemeral, ignores the user's config and rules, and starts in
an empty directory so no AGENTS.md is discovered. Authentication is the CLI's own login; this adapter
reads no credentials.
"""
import json

from pr_agent_cli_handlers.base import CliAIHandler, CliCommand, CliResponse
from pr_agent_cli_handlers.errors import CliHandlerError

CODEX_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
# Current Codex models reject "minimal", and gpt-6-astra also rejects "none"; map both to "low".
CODEX_EFFORT_ALIASES = {"none": "low", "minimal": "low"}
# Switch off every tool that runs commands, reads files or reaches the network; measured on codex-cli 0.156.1.
CODEX_DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "browser_use", "computer_use", "apps", "plugins", "view_image",
    "image_generation", "in_app_browser",
)


def toml_basic_string(text: str) -> str:
    """Quote text as a TOML basic string so a ``--config key=value`` override carries it verbatim."""
    escaped = []
    for char in text:
        if char == "\\":
            escaped.append("\\\\")
        elif char == '"':
            escaped.append('\\"')
        elif char == "\n":
            escaped.append("\\n")
        elif char == "\r":
            escaped.append("\\r")
        elif char == "\t":
            escaped.append("\\t")
        elif ord(char) < 0x20 or char == "\x7f":
            escaped.append(f"\\u{ord(char):04X}")
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'


class CodexAIHandler(CliAIHandler):
    default_binary = "codex"
    credential_env = frozenset({"OPENAI_API_KEY", "CODEX_API_KEY"})
    config_env = frozenset({"OPENAI_BASE_URL", "CODEX_HOME"})

    def __init__(self):
        super().__init__()
        self.workdir = self.create_workdir("pr-agent-codex-")

    def build_command(self, model: str, system: str, user: str) -> CliCommand:
        argv = [self.binary, "--ask-for-approval", "never", "--sandbox", "read-only", "--model", model]
        for feature in CODEX_DISABLED_FEATURES:
            argv += ["--config", f"features.{feature}=false"]
        argv += ["--config", "developer_instructions=" + toml_basic_string(system)]
        effort = self.reasoning_effort()
        effort = CODEX_EFFORT_ALIASES.get(effort, effort)
        if effort in CODEX_EFFORTS:
            argv += ["--config", f'model_reasoning_effort="{effort}"']
        argv += [
            "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules",
            "--skip-git-repo-check", "--color", "never", "--cd", self.workdir,
        ]
        argv += self.extra_args
        argv.append("-")
        return CliCommand(argv=argv, stdin=user)

    def parse_response(self, stdout: str) -> CliResponse:
        text = None
        prompt_tokens = completion_tokens = 0
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind in ("error", "turn.failed"):
                detail = event.get("message") or event.get("error") or event
                raise CliHandlerError(f"Codex reported a failure: {str(detail)[:500]}")
            item = event.get("item")
            if kind == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text") or ""
            elif kind == "turn.completed":
                usage = event.get("usage")
                usage = usage if isinstance(usage, dict) else {}
                prompt_tokens = int(usage.get("input_tokens") or 0)
                completion_tokens = (int(usage.get("output_tokens") or 0)
                                     + int(usage.get("reasoning_output_tokens") or 0))
        if text is None:
            raise CliHandlerError("Codex produced no agent message")
        return CliResponse(text=text, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run ruff check --fix tests/test_codex.py && uv run pytest -q && uv run ruff check`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/pr_agent_cli_handlers/codex.py tests/test_codex.py && \
  git commit -m "feat: add the Codex adapter with its tool features switched off" -- \
  src/pr_agent_cli_handlers/codex.py tests/test_codex.py
```

---

### Task 6: Activation, console command, seam scan and smoke script

**Files:**
- Create: `src/pr_agent_cli_handlers/activation.py`, `src/pr_agent_cli_handlers/cli.py`, `src/pr_agent_cli_handlers/seam_scan.py`
- Modify: `tests/conftest.py` (add the `restore_seams` fixture)
- Test: `tests/test_activation.py`, `tests/test_cli.py`, `tests/test_seam_scan.py`
- Create: `scripts/smoke`, `scripts/samples/python_off_by_one.diff`, `scripts/samples/js_missing_await.diff`, `scripts/samples/config_timeout.diff`

**Interfaces:**
- Consumes: Tasks 2 to 5 (`HANDLER_VAR`, `CliAIHandler`, `ClaudeCodeAIHandler`, `CodexAIHandler`, `CliHandlerError`).
- Produces, in `pr_agent_cli_handlers.activation`: `@dataclass(frozen=True) Seam(module: str, qualname: str, required: bool)`; `SEAMS: tuple[Seam, ...]` (eleven entries); `DIRECT_CONSTRUCTIONS: tuple[str, ...]`; `HANDLERS: dict[str, tuple[str, str]]` (`claude_code`, `codex`; Task 7 adds `agy`); `class ActivationError(RuntimeError)`; `pr_agent_version() -> str`; `select_handler(environ: Mapping[str, str]) -> type[CliAIHandler]`; `activate(handler_cls: type) -> list[str]` (warnings). In `pr_agent_cli_handlers.cli`: `main(argv: Optional[list[str]] = None) -> int`, `entrypoint() -> None`. In `pr_agent_cli_handlers.seam_scan`: `scan(package_dir: Path) -> tuple[set[tuple[str, str]], set[str]]`, `drift(package_dir: Path) -> list[str]`, `main(argv: Optional[list[str]] = None) -> int`. `scripts/smoke <handler> <model> [diff-file ...]`.

- [ ] **Step 1: Add the `restore_seams` fixture**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def restore_seams():
    """Snapshot the ai_handler defaults activation may replace, and put them back after the test."""
    import importlib

    from pr_agent_cli_handlers.activation import SEAMS

    saved = []
    for seam in SEAMS:
        init = getattr(importlib.import_module(seam.module), seam.qualname).__init__
        saved.append((init, init.__defaults__, init.__kwdefaults__))
    yield
    for init, defaults, kwdefaults in saved:
        init.__defaults__ = defaults
        init.__kwdefaults__ = kwdefaults
```

- [ ] **Step 2: Write the failing activation tests**

`tests/test_activation.py`:

```python
import importlib
import inspect
import sys
import types

import pytest
from pr_agent.agent.pr_agent import PRAgent
from pr_agent.algo.ai_handlers.litellm_ai_handler import LiteLLMAIHandler

import pr_agent_cli_handlers.activation as activation
from pr_agent_cli_handlers.activation import ActivationError, Seam, activate, select_handler
from pr_agent_cli_handlers.claude_code import ClaudeCodeAIHandler
from pr_agent_cli_handlers.codex import CodexAIHandler


def _default_of(seam):
    init = getattr(importlib.import_module(seam.module), seam.qualname).__init__
    return inspect.signature(init).parameters["ai_handler"].default


@pytest.mark.parametrize("name, expected", [("claude_code", ClaudeCodeAIHandler), ("codex", CodexAIHandler)])
def test_select_handler_returns_the_named_adapter(name, expected):
    assert select_handler({"PR_AGENT_CLI_HANDLER": f" {name} "}) is expected


@pytest.mark.parametrize("value", [None, "", "  ", "litellm", "Claude_Code"])
def test_select_handler_rejects_unknown_or_unset_names(value):
    environ = {} if value is None else {"PR_AGENT_CLI_HANDLER": value}
    with pytest.raises(ActivationError, match="PR_AGENT_CLI_HANDLER must be one of claude_code, codex"):
        select_handler(environ)


def test_seam_table_lists_the_eleven_known_constructors():
    assert len(activation.SEAMS) == 11
    assert {(s.module, s.qualname) for s in activation.SEAMS if s.required} == {
        ("pr_agent.agent.pr_agent", "PRAgent"),
        ("pr_agent.tools.pr_reviewer", "PRReviewer"),
        ("pr_agent.tools.pr_description", "PRDescription"),
        ("pr_agent.tools.pr_code_suggestions", "PRCodeSuggestions"),
    }


def test_activate_replaces_every_seam_default(restore_seams):
    assert activate(ClaudeCodeAIHandler) == []

    assert all(_default_of(seam) is ClaudeCodeAIHandler for seam in activation.SEAMS)
    assert PRAgent().ai_handler is ClaudeCodeAIHandler


def test_activate_is_repeatable_and_can_switch_handlers(restore_seams):
    activate(ClaudeCodeAIHandler)
    activate(ClaudeCodeAIHandler)
    activate(CodexAIHandler)

    assert all(_default_of(seam) is CodexAIHandler for seam in activation.SEAMS)


def _install_fake_module(monkeypatch, name, cls):
    module = types.ModuleType(name)
    setattr(module, cls.__name__, cls)
    monkeypatch.setitem(sys.modules, name, module)


class _NoSeam:
    def __init__(self, pr_url, args=None):
        self.pr_url = pr_url


def test_missing_required_seam_raises_and_patches_nothing(monkeypatch, restore_seams):
    _install_fake_module(monkeypatch, "fake_seam_module", _NoSeam)
    monkeypatch.setattr(activation, "SEAMS", activation.SEAMS + (Seam("fake_seam_module", "_NoSeam", True),))

    with pytest.raises(ActivationError, match=r"unsupported PR-Agent version: fake_seam_module\._NoSeam"):
        activate(ClaudeCodeAIHandler)

    assert _default_of(activation.SEAMS[0]) is LiteLLMAIHandler


def test_missing_optional_seam_becomes_a_warning(monkeypatch, restore_seams):
    _install_fake_module(monkeypatch, "fake_seam_module", _NoSeam)
    monkeypatch.setattr(activation, "SEAMS", activation.SEAMS + (Seam("fake_seam_module", "_NoSeam", False),))

    warnings = activate(ClaudeCodeAIHandler)

    assert len(warnings) == 1 and "fake_seam_module._NoSeam" in warnings[0]
    assert PRAgent().ai_handler is ClaudeCodeAIHandler


def test_required_seam_import_failure_patches_nothing(monkeypatch, restore_seams):
    missing = Seam("pr_agent_cli_handlers_no_such_module", "Anything", True)
    monkeypatch.setattr(activation, "SEAMS", activation.SEAMS + (missing,))

    with pytest.raises(ActivationError, match="pr_agent_cli_handlers_no_such_module"):
        activate(ClaudeCodeAIHandler)

    assert _default_of(activation.SEAMS[0]) is LiteLLMAIHandler
```

- [ ] **Step 3: Write the failing command and scan tests**

`tests/test_cli.py`:

```python
import inspect

import pr_agent.cli as pr_agent_cli
import pr_agent.servers.github_action_runner as github_action_runner
from pr_agent.agent.pr_agent import PRAgent
from pr_agent.algo.ai_handlers.litellm_ai_handler import LiteLLMAIHandler

from pr_agent_cli_handlers.claude_code import ClaudeCodeAIHandler
from pr_agent_cli_handlers.cli import main


def _pragent_default():
    return inspect.signature(PRAgent.__init__).parameters["ai_handler"].default


def test_main_exits_2_when_the_handler_is_unset(capsys, restore_seams):
    assert main(["--pr_url", "x", "review"]) == 2
    assert "PR_AGENT_CLI_HANDLER" in capsys.readouterr().err
    assert _pragent_default() is LiteLLMAIHandler


def test_main_exits_2_on_invalid_handler_settings_before_activation(monkeypatch, capsys, restore_seams):
    monkeypatch.setenv("PR_AGENT_CLI_HANDLER", "codex")
    monkeypatch.setenv("PR_AGENT_CLI_TIMEOUT", "abc")

    assert main(["--pr_url", "x", "review"]) == 2
    assert "PR_AGENT_CLI_TIMEOUT" in capsys.readouterr().err
    assert _pragent_default() is LiteLLMAIHandler


def test_main_passes_arguments_to_pr_agent_cli_after_activation(monkeypatch, restore_seams):
    seen = {}

    def fake_run(inargs=None, args=None):
        seen["inargs"] = inargs
        seen["default"] = _pragent_default()

    monkeypatch.setattr(pr_agent_cli, "run", fake_run)
    monkeypatch.setenv("PR_AGENT_CLI_HANDLER", "claude_code")

    assert main(["--pr_url", "https://example.test/pr/1", "review"]) == 0
    assert seen == {"inargs": ["--pr_url", "https://example.test/pr/1", "review"], "default": ClaudeCodeAIHandler}


def test_main_returns_the_exit_code_of_pr_agent(monkeypatch, restore_seams):
    monkeypatch.setattr(pr_agent_cli, "run", lambda inargs=None, args=None: 1)
    monkeypatch.setenv("PR_AGENT_CLI_HANDLER", "claude_code")

    assert main(["--pr_url", "x", "review"]) == 1


def test_main_action_runs_the_github_action_runner(monkeypatch, restore_seams):
    calls = []
    monkeypatch.setattr(github_action_runner, "main", lambda: calls.append(_pragent_default()))
    monkeypatch.setenv("PR_AGENT_CLI_HANDLER", "claude_code")

    assert main(["action"]) == 0
    assert calls == [ClaudeCodeAIHandler]
```

`tests/test_seam_scan.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_activation.py tests/test_cli.py tests/test_seam_scan.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pr_agent_cli_handlers.activation'`

- [ ] **Step 5: Write the activation module**

`src/pr_agent_cli_handlers/activation.py`:

```python
"""Point PR-Agent's AI handler defaults at a CLI-backed handler for the current process.

PR-Agent has no configuration switch for the AI handler: PRAgent and each tool class take an
``ai_handler`` factory whose default is LiteLLMAIHandler, and the entrypoints construct them with that
default (the GitHub Action runner constructs PRReviewer, PRDescription and PRCodeSuggestions directly).
Check that every such default still has that shape, then replace it.
"""
import importlib
import inspect
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Mapping

from pr_agent_cli_handlers.environment import HANDLER_VAR


@dataclass(frozen=True)
class Seam:
    module: str
    qualname: str
    required: bool


# Keep in step with seam_scan: it fails when PR-Agent gains or loses one of these.
SEAMS = (
    Seam("pr_agent.agent.pr_agent", "PRAgent", True),
    Seam("pr_agent.tools.pr_reviewer", "PRReviewer", True),
    Seam("pr_agent.tools.pr_description", "PRDescription", True),
    Seam("pr_agent.tools.pr_code_suggestions", "PRCodeSuggestions", True),
    Seam("pr_agent.tools.pr_questions", "PRQuestions", False),
    Seam("pr_agent.tools.pr_line_questions", "PR_LineQuestions", False),
    Seam("pr_agent.tools.pr_update_changelog", "PRUpdateChangelog", False),
    Seam("pr_agent.tools.pr_add_docs", "PRAddDocs", False),
    Seam("pr_agent.tools.pr_generate_labels", "PRGenerateLabels", False),
    Seam("pr_agent.tools.pr_help_message", "PRHelpMessage", False),
    Seam("pr_agent.tools.pr_help_docs", "PRHelpDocs", False),
)
# Construct LiteLLMAIHandler() directly in these files; they stay outside the supported surface.
DIRECT_CONSTRUCTIONS = ("pr_agent/mosaico/executor.py",)

HANDLERS = {
    "claude_code": ("pr_agent_cli_handlers.claude_code", "ClaudeCodeAIHandler"),
    "codex": ("pr_agent_cli_handlers.codex", "CodexAIHandler"),
}


class ActivationError(RuntimeError):
    """Stop before PR-Agent starts: the handler choice is invalid or a required seam is missing."""


def pr_agent_version() -> str:
    """Return the installed PR-Agent version, or "unknown"."""
    try:
        return version("pr-agent")
    except PackageNotFoundError:
        return "unknown"


def select_handler(environ: Mapping[str, str]):
    """Return the handler class PR_AGENT_CLI_HANDLER names."""
    name = environ.get(HANDLER_VAR, "").strip()
    if name not in HANDLERS:
        shown = repr(name) if name else "unset"
        raise ActivationError(f"{HANDLER_VAR} must be one of {', '.join(sorted(HANDLERS))}; it is {shown}")
    module_name, class_name = HANDLERS[name]
    return getattr(importlib.import_module(module_name), class_name)


def _replaceable(default) -> bool:
    """Return whether ``default`` is LiteLLMAIHandler or a handler an earlier activation installed."""
    from pr_agent.algo.ai_handlers.litellm_ai_handler import LiteLLMAIHandler

    from pr_agent_cli_handlers.base import CliAIHandler

    return default is LiteLLMAIHandler or (isinstance(default, type) and issubclass(default, CliAIHandler))


def _default_slot(init):
    """Return where ``init`` keeps its ai_handler default, ("positional", index) or ("keyword", name), or None."""
    try:
        parameters = inspect.signature(init).parameters
    except (TypeError, ValueError):
        return None
    parameter = parameters.get("ai_handler")
    if parameter is None or not _replaceable(parameter.default):
        return None
    if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
        return ("keyword", "ai_handler")
    with_defaults = [
        p for p in parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and p.default is not inspect.Parameter.empty
    ]
    return ("positional", with_defaults.index(parameter))


def activate(handler_cls) -> list[str]:
    """Replace every seam's ai_handler default with ``handler_cls``; return warnings for optional seams.

    Check every seam before replacing any default, so a missing required seam leaves PR-Agent untouched.
    """
    targets = []
    warnings = []
    for seam in SEAMS:
        try:
            init = getattr(importlib.import_module(seam.module), seam.qualname).__init__
        except (ImportError, AttributeError) as e:
            slot, reason = None, f"{type(e).__name__}: {e}"
        else:
            slot, reason = _default_slot(init), "no ai_handler parameter defaulting to LiteLLMAIHandler"
        if slot is None:
            message = f"{seam.module}.{seam.qualname}: {reason} (pr-agent {pr_agent_version()})"
            if seam.required:
                raise ActivationError(f"unsupported PR-Agent version: {message}")
            warnings.append(message)
            continue
        targets.append((init, slot))
    for init, (kind, where) in targets:
        if kind == "keyword":
            init.__kwdefaults__ = {**init.__kwdefaults__, where: handler_cls}
        else:
            defaults = list(init.__defaults__)
            defaults[where] = handler_cls
            init.__defaults__ = tuple(defaults)
    return warnings
```

- [ ] **Step 6: Write the console command**

`src/pr_agent_cli_handlers/cli.py`:

```python
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
```

- [ ] **Step 7: Write the seam scan**

`src/pr_agent_cli_handlers/seam_scan.py`:

```python
"""Read PR-Agent's source and report drift from the activation table.

Run ``python -m pr_agent_cli_handlers.seam_scan [PR_AGENT_PACKAGE_DIR]``. Exit 1 when PR-Agent gained or
lost an ``ai_handler`` default of LiteLLMAIHandler, or a direct ``LiteLLMAIHandler()`` call.
"""
import ast
import sys
from pathlib import Path
from typing import Optional

from pr_agent_cli_handlers.activation import DIRECT_CONSTRUCTIONS, SEAMS


def _has_litellm_default(args: ast.arguments) -> bool:
    positional = args.posonlyargs + args.args
    pairs = list(zip(positional[len(positional) - len(args.defaults):], args.defaults, strict=True))
    pairs += [(arg, default) for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
              if default is not None]
    return any(arg.arg == "ai_handler" and isinstance(default, ast.Name) and default.id == "LiteLLMAIHandler"
               for arg, default in pairs)


def scan(package_dir: Path) -> tuple[set[tuple[str, str]], set[str]]:
    """Return the (module, class) pairs whose __init__ defaults ai_handler to LiteLLMAIHandler, and the
    package-relative files that call LiteLLMAIHandler() directly."""
    defaults: set[tuple[str, str]] = set()
    direct: set[str] = set()
    root = package_dir.parent
    for path in sorted(package_dir.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        module = relative[: -len(".py")].replace("/", ".").removesuffix(".__init__")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if (isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__"
                            and _has_litellm_default(item.args)):
                        defaults.add((module, node.name))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "LiteLLMAIHandler":
                direct.add(relative)
    return defaults, direct


def drift(package_dir: Path) -> list[str]:
    """Return one message per difference between ``package_dir`` and the activation table."""
    defaults, direct = scan(package_dir)
    expected_defaults = {(seam.module, seam.qualname) for seam in SEAMS}
    expected_direct = set(DIRECT_CONSTRUCTIONS)
    messages = [f"new seam not handled: {m}.{c}.__init__" for m, c in sorted(defaults - expected_defaults)]
    messages += [f"seam gone: {m}.{c}.__init__" for m, c in sorted(expected_defaults - defaults)]
    messages += [f"new direct LiteLLMAIHandler() call: {f}" for f in sorted(direct - expected_direct)]
    messages += [f"direct LiteLLMAIHandler() call gone: {f}" for f in sorted(expected_direct - direct)]
    return messages


def main(argv: Optional[list[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        package_dir = Path(args[0])
    else:
        import pr_agent

        package_dir = Path(pr_agent.__file__).parent
    messages = drift(package_dir)
    for message in messages:
        print(message)
    return 1 if messages else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check`
Expected: all tests pass; `All checks passed!` If `test_installed_pr_agent_matches_the_activation_table` fails, the installed PR-Agent differs from the table taken from the 0.46.0 source: stop and report the printed drift as DONE_WITH_CONCERNS instead of editing the table to match.

- [ ] **Step 9: Write the smoke script and samples**

`scripts/smoke` (make it executable with `chmod +x scripts/smoke`):

```bash
#!/usr/bin/env bash
# Run PR-Agent's review through one CLI handler against sample diffs. Uses the real CLI and its login;
# run it by hand before a release, never in CI.
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: scripts/smoke <claude_code|codex|agy> <model> [diff-file ...]" >&2
  exit 2
fi
handler=$1
model=$2
shift 2
root=$(cd "$(dirname "$0")/.." && pwd)
if [ "$#" -eq 0 ]; then
  set -- "$root"/scripts/samples/*.diff
fi
out=$(mktemp -d)
export LITELLM_LOCAL_MODEL_COST_MAP=True
export PR_AGENT_CLI_HANDLER="$handler"
export CONFIG__MODEL="$model"
export CONFIG__FALLBACK_MODELS='[]'
export CONFIG__CUSTOM_MODEL_MAX_TOKENS=200000

status=0
for diff in "$@"; do
  name=$(basename "$diff" .diff)
  if uv run --project "$root" pr-agent-cli-handlers --diff-file "$diff" --json-output "$out/$name.json" review \
      >"$out/$name.md" 2>"$out/$name.log" \
    && python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); sys.exit(0 if isinstance(d, dict) and d else 1)' \
      "$out/$name.json"; then
    echo "ok   $name"
  else
    echo "FAIL $name (output and logs in $out)"
    status=1
  fi
done
exit "$status"
```

`scripts/samples/python_off_by_one.diff`:

```diff
diff --git a/src/pagination.py b/src/pagination.py
index 3b18e51..9c2f7a1 100644
--- a/src/pagination.py
+++ b/src/pagination.py
@@ -1,5 +1,5 @@
 def page_bounds(page: int, per_page: int, total: int) -> tuple[int, int]:
     """Return the start and end index of a 1-based page."""
-    start = (page - 1) * per_page
-    end = min(start + per_page, total)
+    start = page * per_page
+    end = min(start + per_page, total) - 1
     return start, end
```

`scripts/samples/js_missing_await.diff`:

```diff
diff --git a/web/api.js b/web/api.js
index 1a2b3c4..5d6e7f8 100644
--- a/web/api.js
+++ b/web/api.js
@@ -1,6 +1,6 @@
 export async function loadUser(client, id) {
-  const response = await client.get(`/users/${id}`);
+  const response = client.get(`/users/${id}`);
   if (!response.ok) {
     throw new Error(`HTTP ${response.status}`);
   }
   return response.json();
```

`scripts/samples/config_timeout.diff`:

```diff
diff --git a/config/settings.toml b/config/settings.toml
index 0f1e2d3..4c5b6a7 100644
--- a/config/settings.toml
+++ b/config/settings.toml
@@ -1,4 +1,5 @@
 [http]
-timeout_seconds = 30
+timeout_seconds = 0
+retries = -1
 user_agent = "example/1.0"
 verify_tls = true
```

- [ ] **Step 10: Live smoke run (real CLIs; uses the logged-in subscriptions on this machine)**

Run: `scripts/smoke claude_code claude-sonnet-5 && scripts/smoke codex gpt-6-astra`
Expected: `ok   config_timeout`, `ok   js_missing_await`, `ok   python_off_by_one` for each handler. Record the output in the report. If a run fails, include the `.log` tail in the report and report DONE_WITH_CONCERNS; do not change adapter argv to make it pass.

- [ ] **Step 11: Commit**

```bash
git add src/pr_agent_cli_handlers/activation.py src/pr_agent_cli_handlers/cli.py src/pr_agent_cli_handlers/seam_scan.py \
  tests/conftest.py tests/test_activation.py tests/test_cli.py tests/test_seam_scan.py scripts && \
  git commit -m "feat: activate the selected CLI handler and run PR-Agent" -- \
  src/pr_agent_cli_handlers/activation.py src/pr_agent_cli_handlers/cli.py src/pr_agent_cli_handlers/seam_scan.py \
  tests/conftest.py tests/test_activation.py tests/test_cli.py tests/test_seam_scan.py scripts
```

---

### Task 7: Antigravity adapter and the P3 gate

**Files:**
- Create: `src/pr_agent_cli_handlers/agy.py`
- Modify: `src/pr_agent_cli_handlers/activation.py` (`HANDLERS`)
- Modify: `tests/test_activation.py` (handler list expectations)
- Test: `tests/test_agy.py`

**Interfaces:**
- Consumes: Task 3's base (`create_workdir`, `CliCommand.cwd`); Task 4's `fake_cli`; Task 6's `HANDLERS` and `scripts/smoke`.
- Produces: `pr_agent_cli_handlers.agy.AgyAIHandler` (`default_binary = "agy"`, attribute `workdir`), constants `AGY_EFFORTS`, `AGY_EFFORT_ALIASES`; `HANDLERS["agy"]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_agy.py`:

```python
import json
import os
from types import SimpleNamespace

import pytest

import pr_agent_cli_handlers.base as cli_module
from pr_agent_cli_handlers.agy import AgyAIHandler
from pr_agent_cli_handlers.errors import CliHandlerError


class _FakeSettings:
    def __init__(self, values=None):
        self.values = values or {}
        self.config = SimpleNamespace(ai_timeout=30)

    def get(self, key, default=None):
        return self.values.get(key, default)


def _install_settings(monkeypatch, values=None):
    monkeypatch.setattr(cli_module, "get_settings", lambda: _FakeSettings(values))


def _lines(*events):
    return "\n".join(json.dumps(event) for event in events) + "\n"


def _result(**overrides):
    result = {"conversation_id": "c1", "status": "SUCCESS", "response": "review text\n",
              "usage": {"input_tokens": 12605, "output_tokens": 25, "thinking_tokens": 24, "total_tokens": 12630}}
    result.update(overrides)
    return {"event": "result", "result": result}


def test_build_command_uses_stream_json_on_stdin_in_an_empty_workdir(monkeypatch):
    _install_settings(monkeypatch, {"CONFIG.REASONING_EFFORT": "medium"})
    monkeypatch.setenv("PR_AGENT_CLI_EXTRA_ARGS", "--log-file /tmp/agy.log")
    handler = AgyAIHandler()

    command = handler.build_command("gemini-3.8-pro", "SYS", "USER")

    assert command.argv == [
        "agy", "--disable-slash-commands", "--sandbox", "--input-format", "stream-json", "--output-format",
        "stream-json", "--model", "gemini-3.8-pro", "--effort", "medium", "--log-file", "/tmp/agy.log",
    ]
    assert json.loads(command.stdin) == {"event": "user", "message": {"content": "SYS\n\nUSER"}}
    assert command.stdin.endswith("\n")
    assert command.cwd == handler.workdir


@pytest.mark.parametrize("effort, expected", [
    ("none", "low"), ("minimal", "low"), ("low", "low"), ("medium", "medium"), ("high", "high"),
    ("xhigh", "high"), ("max", "high"), ("MAX", "high"),
])
def test_build_command_maps_reasoning_effort(monkeypatch, effort, expected):
    _install_settings(monkeypatch, {"CONFIG.REASONING_EFFORT": effort})
    argv = AgyAIHandler().build_command("m", "S", "U").argv
    assert argv[argv.index("--effort") + 1] == expected


def test_build_command_skips_unknown_effort(monkeypatch):
    _install_settings(monkeypatch, {"CONFIG.REASONING_EFFORT": "turbo"})
    assert "--effort" not in AgyAIHandler().build_command("m", "S", "U").argv


def test_parse_response_reads_the_result_line(monkeypatch):
    _install_settings(monkeypatch)
    stdout = _lines({"event": "step_update", "step_update": {"state": "DONE"}}, _result())

    response = AgyAIHandler().parse_response(stdout)

    assert (response.text, response.prompt_tokens, response.completion_tokens) == ("review text\n", 12605, 25)
    assert response.cost_usd is None


def test_parse_response_uses_the_last_result_line(monkeypatch):
    _install_settings(monkeypatch)
    stdout = _lines(_result(response="first"), {"event": "result", "result": "not-a-dict"}, None, 42,
                    _result(response="last"))

    assert AgyAIHandler().parse_response(stdout).text == "last"


def test_parse_response_raises_without_a_result_line(monkeypatch):
    _install_settings(monkeypatch)
    with pytest.raises(CliHandlerError, match="no result"):
        AgyAIHandler().parse_response(_lines({"event": "step_update"}) + "not json\n")


def test_parse_response_raises_on_a_failed_status(monkeypatch):
    _install_settings(monkeypatch)
    with pytest.raises(CliHandlerError, match="ERROR: quota exhausted"):
        AgyAIHandler().parse_response(_lines(_result(status="ERROR", error="quota exhausted", response="")))


def test_agy_names_its_credential_variable():
    assert AgyAIHandler.credential_env == {"GEMINI_API_KEY"}
    assert AgyAIHandler.config_env == frozenset()


async def test_contract_runs_the_agy_binary_in_its_workdir(monkeypatch, fake_cli):
    _install_settings(monkeypatch)
    record = fake_cli("agy", _lines(_result(response="looks good")))
    handler = AgyAIHandler()

    text, finish_reason = await handler.chat_completion(model="gemini-3.8-pro", system="SYS", user="USER")

    recorded = json.loads(record.read_text())
    assert (text, finish_reason) == ("looks good", "stop")
    assert recorded["argv"] == handler.build_command("gemini-3.8-pro", "SYS", "USER").argv[1:]
    assert json.loads(recorded["stdin"]) == {"event": "user", "message": {"content": "SYS\n\nUSER"}}
    assert os.path.realpath(recorded["cwd"]) == os.path.realpath(handler.workdir)
```

In `tests/test_activation.py`, change the parametrize list of `test_select_handler_returns_the_named_adapter` to include `("agy", AgyAIHandler)` (add `from pr_agent_cli_handlers.agy import AgyAIHandler`), and change the expected message in `test_select_handler_rejects_unknown_or_unset_names` to `"PR_AGENT_CLI_HANDLER must be one of agy, claude_code, codex"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agy.py tests/test_activation.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pr_agent_cli_handlers.agy'`

- [ ] **Step 3: Write the adapter**

`src/pr_agent_cli_handlers/agy.py`:

```python
"""Run the Antigravity CLI (``agy``) headless once per call. Experimental.

``agy`` has no system-prompt override and no switch to disable its tools, so PR-Agent's system prompt
travels inside the user message and the CLI keeps file access: use this adapter on trusted repositories
only. The stream-json form reads the prompt from stdin, so no prompt appears in the argument list;
slash commands are disabled so text such as ``/review`` inside a prompt is not expanded.
"""
import json

from pr_agent_cli_handlers.base import CliAIHandler, CliCommand, CliResponse
from pr_agent_cli_handlers.errors import CliHandlerError

AGY_EFFORTS = frozenset({"low", "medium", "high"})
AGY_EFFORT_ALIASES = {"xhigh": "high", "max": "high", "none": "low", "minimal": "low"}


class AgyAIHandler(CliAIHandler):
    default_binary = "agy"
    credential_env = frozenset({"GEMINI_API_KEY"})

    def __init__(self):
        super().__init__()
        self.workdir = self.create_workdir("pr-agent-agy-")

    def build_command(self, model: str, system: str, user: str) -> CliCommand:
        argv = [
            self.binary, "--disable-slash-commands", "--sandbox",
            "--input-format", "stream-json", "--output-format", "stream-json", "--model", model,
        ]
        effort = self.reasoning_effort()
        effort = AGY_EFFORT_ALIASES.get(effort, effort)
        if effort in AGY_EFFORTS:
            argv += ["--effort", effort]
        argv += self.extra_args
        message = {"event": "user", "message": {"content": f"{system}\n\n{user}"}}
        return CliCommand(argv=argv, stdin=json.dumps(message) + "\n", cwd=self.workdir)

    def parse_response(self, stdout: str) -> CliResponse:
        result = None
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("event") == "result" and isinstance(event.get("result"), dict):
                result = event["result"]
        if result is None:
            raise CliHandlerError("Antigravity CLI produced no result")
        status = result.get("status")
        if status != "SUCCESS":
            message = f"Antigravity CLI reported {status or 'no status'}"
            if result.get("error"):
                message += f": {str(result['error'])[:500]}"
            raise CliHandlerError(message)
        usage = result.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        return CliResponse(text=result.get("response") or "",
                           prompt_tokens=int(usage.get("input_tokens") or 0),
                           completion_tokens=int(usage.get("output_tokens") or 0))
```

In `src/pr_agent_cli_handlers/activation.py`, add the entry `"agy": ("pr_agent_cli_handlers.agy", "AgyAIHandler"),` to `HANDLERS`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 5: Run the P3 gate (real `agy`; uses the logged-in account on this machine)**

Run: `agy models` and pick the first listed model slug; then `scripts/smoke agy <that slug>`.
Expected: `ok` for all three samples. Record the slug and the output in the report.
If any sample fails: run `git restore src/pr_agent_cli_handlers/activation.py tests/test_activation.py` (so `agy` is not selectable), commit only `agy.py` and `tests/test_agy.py` under the title `feat: add the experimental Antigravity adapter (not selectable)`, and report BLOCKED with the failing `.log` tails; the controller rules on shipping.

- [ ] **Step 6: Commit**

```bash
git add src/pr_agent_cli_handlers/agy.py src/pr_agent_cli_handlers/activation.py tests/test_agy.py tests/test_activation.py && \
  git commit -m "feat: add the experimental Antigravity adapter" -- \
  src/pr_agent_cli_handlers/agy.py src/pr_agent_cli_handlers/activation.py tests/test_agy.py tests/test_activation.py
```

---

### Task 8: GitHub Action, GitLab template, README and changelog

**Files:**
- Create: `action.yml`, `templates/gitlab-ci.yml`, `CHANGELOG.md`
- Modify: `README.md` (replace the stub)
- Test: `tests/test_distribution.py`

**Interfaces:**
- Consumes: the console command `pr-agent-cli-handlers` and its `action` form (Task 6); handler names (Tasks 6 and 7).
- Produces: a composite GitHub Action with inputs `handler`, `model`, `cli-version`, `package-version`; a GitLab job template `pr-agent-cli-handlers`; pinned CLI versions `2.1.280` (Claude Code) and `0.156.1` (Codex) in both files.

- [ ] **Step 1: Write the failing tests**

`tests/test_distribution.py`:

```python
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
                 "PR_AGENT_CLI_PASS_ENV", "claude_code", "codex", "agy"):
        assert name in readme
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_distribution.py -q`
Expected: FAIL with `FileNotFoundError` for `action.yml`

- [ ] **Step 3: Write the action**

`action.yml`:

```yaml
name: "PR-Agent through agent CLIs"
description: "Run PR-Agent reviews through the Claude Code, Codex or Antigravity CLI instead of LiteLLM API calls"
branding:
  icon: "check-circle"
  color: "blue"
inputs:
  handler:
    description: "CLI handler: claude_code, codex or agy"
    required: true
  model:
    description: "Model for PR-Agent (config.model); must be a model the selected CLI accepts"
    required: true
  cli-version:
    description: "CLI version; empty uses the pinned version for claude_code and codex. agy always installs its latest release"
    required: false
    default: ""
  package-version:
    description: "pr-agent-cli-handlers version to install; empty installs the latest release"
    required: false
    default: ""
runs:
  using: composite
  steps:
    - uses: actions/setup-python@v5
      with:
        python-version: "3.12"
    - uses: actions/setup-node@v4
      if: inputs.handler != 'agy'
      with:
        node-version: "22"
    - name: Install pr-agent-cli-handlers
      shell: bash
      env:
        PACKAGE_VERSION: ${{ inputs.package-version }}
      run: pip install "pr-agent-cli-handlers${PACKAGE_VERSION:+==$PACKAGE_VERSION}"
    - name: Install the agent CLI
      shell: bash
      env:
        HANDLER: ${{ inputs.handler }}
        CLI_VERSION: ${{ inputs.cli-version }}
      run: |
        case "$HANDLER" in
          claude_code) npm install -g "@anthropic-ai/claude-code@${CLI_VERSION:-2.1.280}" ;;
          codex) npm install -g "@openai/codex@${CLI_VERSION:-0.156.1}" ;;
          agy)
            curl -fsSL https://antigravity.google/cli/install.sh | bash
            echo "$HOME/.local/bin" >> "$GITHUB_PATH"
            if [ -n "${GEMINI_API_KEY:-}" ]; then
              mkdir -p "$HOME/.gemini/antigravity-cli"
              printf '{"modelProvider": "gemini"}\n' > "$HOME/.gemini/antigravity-cli/settings.json"
            fi
            ;;
          *) echo "unknown handler: $HANDLER" >&2; exit 2 ;;
        esac
    - name: Run PR-Agent
      shell: bash
      env:
        PR_AGENT_CLI_HANDLER: ${{ inputs.handler }}
        CONFIG__MODEL: ${{ inputs.model }}
      run: pr-agent-cli-handlers action
```

- [ ] **Step 4: Write the GitLab template**

`templates/gitlab-ci.yml`:

```yaml
# Include with `include: remote: https://raw.githubusercontent.com/akalongman/pr-agent-cli-handlers/<tag>/templates/gitlab-ci.yml`
# or copy this job. Set GITLAB_PERSONAL_ACCESS_TOKEN and the CLI credential as masked, protected CI/CD variables.
pr-agent-cli-handlers:
  stage: test
  image: node:22-bookworm
  variables:
    PR_AGENT_CLI_HANDLER: claude_code
    CONFIG__MODEL: claude-sonnet-5
    CLI_VERSION: ""
    PACKAGE_VERSION: ""
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
  script:
    - curl -LsSf https://astral.sh/uv/install.sh | sh
    - export PATH="$HOME/.local/bin:$PATH"
    - uv tool install --python 3.12 "pr-agent-cli-handlers${PACKAGE_VERSION:+==$PACKAGE_VERSION}"
    - |
      case "$PR_AGENT_CLI_HANDLER" in
        claude_code) npm install -g "@anthropic-ai/claude-code@${CLI_VERSION:-2.1.280}" ;;
        codex) npm install -g "@openai/codex@${CLI_VERSION:-0.156.1}" ;;
        agy)
          curl -fsSL https://antigravity.google/cli/install.sh | bash
          if [ -n "${GEMINI_API_KEY:-}" ]; then
            mkdir -p "$HOME/.gemini/antigravity-cli"
            printf '{"modelProvider": "gemini"}\n' > "$HOME/.gemini/antigravity-cli/settings.json"
          fi
          ;;
        *) echo "unknown handler: $PR_AGENT_CLI_HANDLER" >&2; exit 2 ;;
      esac
    - export MR_URL="$CI_MERGE_REQUEST_PROJECT_URL/merge_requests/$CI_MERGE_REQUEST_IID"
    - export gitlab__url="$CI_SERVER_PROTOCOL://$CI_SERVER_FQDN"
    - export gitlab__PERSONAL_ACCESS_TOKEN="$GITLAB_PERSONAL_ACCESS_TOKEN"
    - export config__git_provider="gitlab"
    - pr-agent-cli-handlers --pr_url="$MR_URL" describe
    - pr-agent-cli-handlers --pr_url="$MR_URL" review
    - pr-agent-cli-handlers --pr_url="$MR_URL" improve
```

- [ ] **Step 5: Write the README**

Replace `README.md` with:

````markdown
# pr-agent-cli-handlers

Run [PR-Agent](https://github.com/The-PR-Agent/pr-agent) through a local agent CLI (the Claude Code CLI, the
OpenAI Codex CLI, or experimentally the Antigravity CLI `agy`) instead of LiteLLM API calls. Review pull
requests and merge requests with a subscription you already have, or with an API key, locally or in your
own CI, with no server and no fork of PR-Agent.

This project is not affiliated with Anthropic, OpenAI, Google or the PR-Agent maintainers. It runs each
vendor's published CLI unmodified and never reads, stores or forwards your credentials.

## How it works

`pr-agent-cli-handlers` installs PR-Agent as a dependency and replaces the default AI handler of PR-Agent's
commands with a handler that runs the selected CLI once per model call, so `describe`, `review`, `improve`,
`ask` and the other commands send their model calls through that CLI. Code paths that call LiteLLM directly,
such as MOSAICO, are not covered. The command stops with exit status 2 if the installed PR-Agent no longer
has the constructors it relies on.

## Install

The CLI you choose must be installed and logged in on the same machine.

| Platform | Install this package | Claude Code CLI | Codex CLI | Antigravity CLI |
|---|---|---|---|---|
| macOS | `brew install uv && uv tool install pr-agent-cli-handlers` | `npm install -g @anthropic-ai/claude-code` | `npm install -g @openai/codex` | `curl -fsSL https://antigravity.google/cli/install.sh \| bash` |
| Linux (Debian, Ubuntu) | `curl -LsSf https://astral.sh/uv/install.sh \| sh && uv tool install pr-agent-cli-handlers` | `npm install -g @anthropic-ai/claude-code` | `npm install -g @openai/codex` | `curl -fsSL https://antigravity.google/cli/install.sh \| bash` |
| Linux (other) | `pipx install pr-agent-cli-handlers` (Python 3.12 or later) | as above | as above | as above |
| Windows (PowerShell) | `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"; uv tool install pr-agent-cli-handlers` | `npm install -g @anthropic-ai/claude-code` | `npm install -g @openai/codex` | `irm https://antigravity.google/cli/install.ps1 \| iex` |
| WSL | follow the Linux rows inside your WSL distribution | as Linux | as Linux | as Linux |

## Quick start

```bash
export PR_AGENT_CLI_HANDLER=claude_code
export CONFIG__MODEL=claude-sonnet-5
export CONFIG__FALLBACK_MODELS='["claude-opus-5"]'
export GITHUB__USER_TOKEN=<a GitHub token that can read and comment on the pull request>
pr-agent-cli-handlers --pr_url https://github.com/<owner>/<repo>/pull/<number> review
```

Review a local diff without any git provider:

```bash
git diff main...HEAD | pr-agent-cli-handlers --stdin review
```

`config.fallback_models` must list models the selected CLI accepts: PR-Agent's default fallback is an OpenAI
model, which the Claude Code handler rejects. For a model PR-Agent does not know, set
`CONFIG__CUSTOM_MODEL_MAX_TOKENS`.

## Configuration

Handler settings come from environment variables only, so a repository's `.pr_agent.toml` cannot change them.

| Variable | Meaning | Default |
|---|---|---|
| `PR_AGENT_CLI_HANDLER` | `claude_code`, `codex` or `agy` | required |
| `PR_AGENT_CLI_BINARY` | CLI executable name or path | `claude`, `codex` or `agy` |
| `PR_AGENT_CLI_EXTRA_ARGS` | extra CLI arguments, split like shell words | empty |
| `PR_AGENT_CLI_TIMEOUT` | seconds per call, a positive number | PR-Agent's `config.ai_timeout` |
| `PR_AGENT_CLI_PASS_ENV` | comma-separated names of extra environment variables to pass to the CLI | empty |

The model, fallback models and reasoning effort come from PR-Agent's own settings (`CONFIG__MODEL`,
`CONFIG__FALLBACK_MODELS`, `CONFIG__REASONING_EFFORT`).

## Credentials

| CLI | Subscription | API key |
|---|---|---|
| Claude Code | `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` (Pro, Max, Team, Enterprise); tied to the person who created it | `ANTHROPIC_API_KEY`, or Bedrock and Vertex through their own variables |
| Codex | ChatGPT login saved by `codex login`; in CI this is experimental | `OPENAI_API_KEY` or `CODEX_API_KEY` |
| `agy` | cached Google-account login; in CI this is experimental | `GEMINI_API_KEY`, plus `{"modelProvider": "gemini"}` in `~/.gemini/antigravity-cli/settings.json` |

Anthropic allows an end user to sign in to the unmodified Claude Code binary with their own subscription, and
states that Pro and Max usage limits assume ordinary, individual usage. For shared or team repositories, use
API keys with spending limits. See the
[Claude Code legal and compliance page](https://code.claude.com/docs/en/legal-and-compliance).

## GitHub Actions

```yaml
on:
  pull_request:
    types: [opened, reopened, ready_for_review, synchronize]
  issue_comment:
jobs:
  pr_agent_job:
    if: ${{ github.event.sender.type != 'Bot' }}
    runs-on: ubuntu-latest
    permissions:
      issues: write
      pull-requests: write
      contents: write
      checks: write
    steps:
      - uses: akalongman/pr-agent-cli-handlers@v0.1.0
        with:
          handler: claude_code
          model: claude-sonnet-5
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          CONFIG__FALLBACK_MODELS: '["claude-opus-5"]'
```

`pull_request` gives fork pull requests no secrets, so they are skipped. `pull_request_target` would review
them with secrets present; the action never checks out pull request code, but a fork's diff can still carry
instructions aimed at the reviewer. Use it only with the Claude Code or Codex handler.

## GitLab

Include `templates/gitlab-ci.yml` from a release tag, or copy its job, and set these masked, protected CI/CD
variables: `GITLAB_PERSONAL_ACCESS_TOKEN` and the CLI credential (for example `CLAUDE_CODE_OAUTH_TOKEN`). Do not
run parent-project pipelines for merge requests from forks while these variables are present.

## Security

- Each CLI receives only an allowlisted environment: process basics, locale, proxies and CA bundles, its own
  credential and configuration variables, and the names in `PR_AGENT_CLI_PASS_ENV`. Git provider tokens such
  as `GITHUB_TOKEN`, `GITLAB__PERSONAL_ACCESS_TOKEN` and `CI_JOB_TOKEN` never reach it.
- Anything a CLI prints is checked for credential values and redacted before PR-Agent sees it. This catches
  exact values only.
- Claude Code runs with its tools switched off, and Codex with its tool features switched off. `agy` cannot
  switch its tools off and can read files on the machine: use it on trusted repositories only.
- Model names must be plain identifiers, because a repository can set `config.model`.

## Limitations

- Webhook servers (GitHub App, GitLab webhook and the others) may work but are not tested yet.
- MOSAICO is not supported: it calls LiteLLM directly.
- The Antigravity adapter is experimental: it has no system-prompt override, so PR-Agent's system prompt
  travels inside the user message.

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check
scripts/smoke claude_code claude-sonnet-5
```

`scripts/smoke` runs real CLIs with your login; run it by hand before a release.

## License

MIT
````

- [ ] **Step 6: Write the changelog**

`CHANGELOG.md`:

```markdown
# Changelog

## 0.1.0 (unreleased)

- Run PR-Agent through the Claude Code CLI and the Codex CLI, and experimentally the Antigravity CLI.
- Read handler settings from `PR_AGENT_CLI_*` environment variables only.
- Pass each CLI an allowlisted environment and redact credential values from its output.
- Add the `pr-agent-cli-handlers` command, a composite GitHub Action and a GitLab pipeline template.
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check`
Expected: all tests pass; `All checks passed!` Then run `grep -n -P '[\x{2013}\x{2014}]' README.md CHANGELOG.md action.yml templates/gitlab-ci.yml` and expect no output.

- [ ] **Step 8: Commit**

```bash
git add action.yml templates/gitlab-ci.yml README.md CHANGELOG.md tests/test_distribution.py && \
  git commit -m "docs: add the GitHub Action, GitLab template and README" -- \
  action.yml templates/gitlab-ci.yml README.md CHANGELOG.md tests/test_distribution.py
```

---

### Task 9: Upstream watch and release workflows

**Files:**
- Create: `.github/workflows/upstream-main.yml`, `.github/workflows/release.yml`
- Modify: `tests/test_distribution.py` (append two tests)

**Interfaces:**
- Consumes: `pr_agent_cli_handlers.seam_scan` (Task 6).
- Produces: a weekly job against PR-Agent's `main`, and tag-triggered publishing to PyPI through trusted publishing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_distribution.py`:

```python
def _workflow(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())


def test_upstream_workflow_runs_weekly_against_pr_agent_main():
    workflow = _workflow("upstream-main.yml")
    triggers = workflow[True]  # YAML 1.1 reads the bare key "on" as a boolean.
    assert "schedule" in triggers and "workflow_dispatch" in triggers
    runs = [step.get("run", "") for step in workflow["jobs"]["upstream-main"]["steps"]]
    assert any("git+https://github.com/The-PR-Agent/pr-agent@main" in run for run in runs)
    assert any("python -m pr_agent_cli_handlers.seam_scan" in run for run in runs)


def test_release_workflow_publishes_through_trusted_publishing():
    workflow = _workflow("release.yml")
    job = workflow["jobs"]["publish"]
    assert workflow[True]["push"]["tags"] == ["v*"]
    assert job["permissions"]["id-token"] == "write"
    uses = [step.get("uses", "") for step in job["steps"]]
    assert "pypa/gh-action-pypi-publish@release/v1" in uses
    assert "password" not in (ROOT / ".github" / "workflows" / "release.yml").read_text()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_distribution.py -q`
Expected: FAIL with `FileNotFoundError` for `upstream-main.yml`

- [ ] **Step 3: Write the workflows**

`.github/workflows/upstream-main.yml`:

```yaml
name: upstream-main

on:
  schedule:
    - cron: "17 6 * * 1"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  upstream-main:
    runs-on: ubuntu-latest
    env:
      LITELLM_LOCAL_MODEL_COST_MAP: "True"
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.12"
      - run: uv sync
      - run: uv pip install --reinstall "pr-agent @ git+https://github.com/The-PR-Agent/pr-agent@main"
      - run: uv run --no-sync python -m pr_agent_cli_handlers.seam_scan
      - run: uv run --no-sync pytest -q
```

`.github/workflows/release.yml`:

```yaml
name: release

on:
  push:
    tags: ["v*"]

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv build
      - uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/upstream-main.yml .github/workflows/release.yml tests/test_distribution.py && \
  git commit -m "ci: watch PR-Agent main weekly and publish releases to PyPI" -- \
  .github/workflows/upstream-main.yml .github/workflows/release.yml tests/test_distribution.py
```

---

## After the plan (not implementer tasks)

- Create the GitHub repository `akalongman/pr-agent-cli-handlers`, push `main`, and configure PyPI trusted publishing for `release.yml` with the environment `pypi`. These are outward-facing steps for the repository owner.
- Probes P5 and P6 (saved Codex and `agy` logins across fresh CI jobs over two days) run after the first release; their results update the README's Credentials table.
