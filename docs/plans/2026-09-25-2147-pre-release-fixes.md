# Pre-release fixes for 0.1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise `CliHandlerError` when a CLI returns an empty answer, stop the GitLab template from falling back to an OpenAI model, and document the PR-Agent settings a CLI job needs.

**Architecture:** `chat_completion` in the base already validates what every adapter's `parse_response` returns, inside one guard; the empty-answer check joins that guard, so all three adapters (and any later one) raise the same way. `CliHandlerError` also subclasses PR-Agent's `FallbackEligibleError`, so `retry_with_fallback_models` moves to the next model on any handler failure. The GitLab template gains one variable, and the README's Configuration section gains the guidance the spec already promises.

**Tech Stack:** Python 3.12, PR-Agent 0.48.0 (Dynaconf settings; the facts below were written against 0.46.0 and re-verified on 0.48.0 on 2026-10-17), pytest with pytest-asyncio (auto mode), uv 0.12.18, PyYAML in tests.

**Spec:** `docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md` (amended by Tasks 1 and 2), and GitHub issues #3, #1 and #2.

## Background (facts and decisions the tasks rely on)

- Today each adapter returns an empty text as a success: Claude Code maps a missing or empty `result` to `""` (`claude_code.py`, `data.get("result") or ""`), Codex accepts an `agent_message` whose `text` is empty, and agy returns `result.get("response") or ""` for a `SUCCESS` status. PR-Agent then fails later on parsing the empty answer, with an error that names the wrong cause (for `/review`, its own `FallbackEligibleError` saying the response held no review mapping, `pr_reviewer.py:1283`). The spec's agy re-gate list (line 189) already requires "a `SUCCESS` result with an empty response raises `CliHandlerError`".
- Decision: the check lives in `CliAIHandler.chat_completion`, inside the existing parse guard, next to the checks that `response.text` is a `str` and `response.models` a tuple of `str`. One check covers the three adapters and any later adapter; each adapter keeps a contract test through its real output shape. Issue #3's "in all three adapters" is met by behavior, not by three copies of the check.
- PR-Agent 0.48.0's `retry_with_fallback_models` (`pr_processing.py:855`) moves to the next model only on `openai.APIError`, `asyncio.TimeoutError` or `FallbackEligibleError` (`algo/token_budget.py`, a `ValueError` subclass) and re-raises anything else. `CliHandlerError` subclasses only `RuntimeError`, so since the 0.48 bump no handler failure (an empty answer, a timeout, a rejected model, a non-zero exit) reaches a fallback model, and R8's "PR-Agent's fallback loop then moves to the next model" does not hold. Found in Task 1's review and verified on 0.48.0 on 2026-10-17.
- Decision (amended 2026-10-17): `CliHandlerError` also subclasses `FallbackEligibleError`, in its own commit after Task 1's first one (Step 8). R1 requires PR-Agent 0.48, where the class exists. A test drives `retry_with_fallback_models` itself, so CI fails if PR-Agent narrows the exceptions it falls back on. A configuration failure (a missing binary) is then retried once per fallback model before the job fails, which R8 already accepts.
- An answer that is only whitespace is empty too. An answer with content keeps its surrounding whitespace: the check tests `text.strip()` but returns `text` unchanged.
- PR-Agent 0.48.0 defaults `config.fallback_models` to `["gpt-5.6-terra"]`, which `ClaudeCodeAIHandler.map_model` rejects ("supports Claude models only"), so every failed primary call with the template's default handler fails twice.
- Decision: the template sets `CONFIG__FALLBACK_MODELS: "[]"`, not a Claude model: the Codex handler checks no model name, so a Claude fallback would fail inside the Codex CLI for a user who switches the handler. `scripts/smoke` already exports the same value.
- PR-Agent reads `config.fallback_models` as a list only when Dynaconf parses the environment value: `pr_processing.py:884-887` (0.48.0; `695-698` in 0.46.0) splits a non-list value on commas, so an unparsed `"[]"` would become a model named `[]`. Verified 2026-09-25 and again 2026-10-17 on 0.48.0: `CONFIG__FALLBACK_MODELS='[]'` yields an empty Dynaconf `DataList`, which is a `list`.
- Decision: no `fallback-models` input on `action.yml`. A default set inside the composite action's step would override a caller's own `CONFIG__FALLBACK_MODELS`, and the README's action example already sets one.
- PR-Agent 0.48.0 facts for the README: `config.ai_timeout` defaults to 120 seconds; `config.custom_model_max_tokens` defaults to -1, and `get_max_tokens` (`algo/token_budget.py`) raises for a model missing from `MAX_TOKENS` unless that setting is positive (`claude-sonnet-5`, `claude-opus-5` and `gpt-6-astra` are known; the alias `opus` is not). PR-Agent's console log goes to standard output.
- The child environment allowlist (`environment.py:86`) is exact names only: base names, the adapter's names and `PR_AGENT_CLI_PASS_ENV`. A CLI switch such as `MAX_THINKING_TOKENS` is dropped unless listed there.
- An effort passed as `--effort` in `PR_AGENT_CLI_EXTRA_ARGS` reaches the CLI after the handler's own, but `CliCommand.effort` records only the effort the adapter derived from `CONFIG__REASONING_EFFORT`, which PR-Agent 0.48.0 defaults to `medium` (`configuration.toml:111`), so the log line names the configured effort, not the one in the extra arguments. (Amended 2026-10-17 after Task 2's review; the first version said the line reads `(effort default)`.)
- `CHANGELOG.md` stays unchanged: both fixes land inside 0.1.0, whose entries already cover the handlers and the template.

## Global Constraints

- Python `>=3.12`. The only runtime dependency is `pr-agent[github,gitlab]>=0.48,<1` (R1; the extras and the cap were added on 2026-10-17, after 0.48.0 moved the git provider SDKs into extras).
- Environment variables, exactly: `PR_AGENT_CLI_HANDLER`, `PR_AGENT_CLI_BINARY`, `PR_AGENT_CLI_EXTRA_ARGS`, `PR_AGENT_CLI_TIMEOUT`, `PR_AGENT_CLI_PASS_ENV`. This plan adds none.
- Every handler failure raises `CliHandlerError` (R8). No command-line argument exceeds 120,000 bytes (R11).
- No automated test runs a real `claude`, `codex` or `agy` binary (R15).
- Ruff rules E, F, B, I at 120 columns; `uv run --locked ruff check` must be clean. Do not run `ruff format`.
- Comments and docstrings are concise and imperative. No em dashes or en dashes anywhere (code, docs, commit messages); hyphens keep their normal use.
- Commits: Conventional Commit titles, signed (never bypass signing), path-limited with `git add <paths> && git commit -m "<title>" -- <paths>`, no trailers, no mention of AI assistants. Never create or switch branches; never push.
- Run tests with `uv run --locked pytest -q <files>`; the gate is `uv lock --check`, `uv run --locked pytest -q` and `uv run --locked ruff check`, run in full before every commit (tests read workflow, template and README files). Local uv is 0.12.18.

## Review Focus

1. An answer of only whitespace (`" "`, `"\n\n"`) must raise like `""`. Pinned in Task 1 (`test_an_empty_answer_surfaces_as_cli_handler_error` and each adapter's contract test).
2. An answer with content and surrounding whitespace must come back unchanged, not stripped. Pinned in Task 1 (`test_an_answer_with_surrounding_whitespace_is_returned_unchanged`).
3. An empty answer cut off at the output limit must say so, since the remedy differs. Pinned in Task 1 (`test_an_empty_answer_at_the_output_limit_says_so`, `test_contract_names_the_output_limit_on_an_empty_answer`).
4. Each adapter's real empty shapes must raise through `chat_completion`: Claude `result` empty or `null`, Codex an empty `agent_message`, agy `SUCCESS` with an empty or `null` response. Pinned in Task 1 (`test_contract_raises_on_an_empty_answer` in each adapter's test file).
5. The template's fallback value must reach PR-Agent as an empty list, not as the string `"[]"`. Pinned in Task 2 (`test_gitlab_template_passes_an_empty_fallback_list_to_pr_agent`).
6. A `CliHandlerError` from the first model must move PR-Agent's `retry_with_fallback_models` to the next model. Pinned in Task 1 Step 8 (`tests/test_errors.py`).

---

### Task 1: An empty answer raises CliHandlerError

**Files:**
- Modify: `src/pr_agent_cli_handlers/base.py` (`chat_completion`, the parse guard)
- Test: `tests/test_base.py`, `tests/test_claude_code.py`, `tests/test_codex.py`, `tests/test_agy.py`
- Modify: `docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md` (R8, the agy re-gate list)
- Modify: `src/pr_agent_cli_handlers/errors.py` (Step 8, amended 2026-10-17)
- Test: `tests/test_errors.py` (Step 8, new)

**Interfaces:**
- Consumes: nothing new. The existing test helpers `_EchoAdapter` and `_install_settings` (`tests/test_base.py`), `_success_payload` (`tests/test_claude_code.py`), `_events` (`tests/test_codex.py`), `_lines` and `_result` (`tests/test_agy.py`), and the `fake_cli` fixture (`tests/conftest.py`).
- Produces: `chat_completion` raises `CliHandlerError("<AdapterClass>: <argv[0]> returned an empty answer")` when `response.text.strip()` is empty, with ` at the output limit` appended when `response.finish_reason == "length"`. After Step 8, `CliHandlerError` is also a `pr_agent.algo.token_budget.FallbackEligibleError`. Task 2 relies on nothing from this task.

- [ ] **Step 1: Write the failing tests**

In `tests/test_base.py`, add after `test_models_that_are_not_a_tuple_of_strings_surface_as_cli_handler_error`:

```python
class _EmptyAnswerAdapter(_EchoAdapter):
    def __init__(self, text, finish_reason="stop"):
        super().__init__()
        self.text = text
        self.finish_reason = finish_reason

    def parse_response(self, stdout):
        return CliResponse(text=self.text, finish_reason=self.finish_reason)


@pytest.mark.parametrize("text", ["", " ", "\n\n", "\t \n"])
async def test_an_empty_answer_surfaces_as_cli_handler_error(monkeypatch, text):
    _install_settings(monkeypatch)

    with pytest.raises(CliHandlerError, match="_EmptyAnswerAdapter: echo-bin returned an empty answer$"):
        await _EmptyAnswerAdapter(text).chat_completion(model="m", system="s", user="u")


async def test_an_empty_answer_at_the_output_limit_says_so(monkeypatch):
    _install_settings(monkeypatch)

    with pytest.raises(CliHandlerError, match="returned an empty answer at the output limit$"):
        await _EmptyAnswerAdapter("", finish_reason="length").chat_completion(model="m", system="s", user="u")


async def test_an_answer_with_surrounding_whitespace_is_returned_unchanged(monkeypatch):
    _install_settings(monkeypatch)

    text, finish_reason = await _EmptyAnswerAdapter("  ok \n").chat_completion(model="m", system="s", user="u")

    assert (text, finish_reason) == ("  ok \n", "stop")
```

In `tests/test_claude_code.py`, add after `test_contract_passes_a_system_prompt_larger_than_one_argument_allows`:

```python
@pytest.mark.parametrize("result", ["", None, "  \n"])
async def test_contract_raises_on_an_empty_answer(monkeypatch, fake_cli, result):
    _install_settings(monkeypatch)
    fake_cli("claude", _success_payload(result=result))

    with pytest.raises(CliHandlerError, match="ClaudeCodeAIHandler: claude returned an empty answer$"):
        await ClaudeCodeAIHandler().chat_completion(model="claude-opus-5", system="SYS", user="USER")


async def test_contract_names_the_output_limit_on_an_empty_answer(monkeypatch, fake_cli):
    _install_settings(monkeypatch)
    fake_cli("claude", _success_payload(result="", stop_reason="max_tokens"))

    with pytest.raises(CliHandlerError, match="claude returned an empty answer at the output limit$"):
        await ClaudeCodeAIHandler().chat_completion(model="claude-opus-5", system="SYS", user="USER")
```

In `tests/test_codex.py`, add after `test_contract_runs_the_codex_binary_with_the_built_command`:

```python
@pytest.mark.parametrize("text", ["", "  \n"])
async def test_contract_raises_on_an_empty_answer(monkeypatch, fake_cli, text):
    _install_settings(monkeypatch)
    fake_cli("codex", _events(
        {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": text}},
        {"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 0}},
    ))

    with pytest.raises(CliHandlerError, match="CodexAIHandler: codex returned an empty answer$"):
        await CodexAIHandler().chat_completion(model="gpt-6-astra", system="SYS", user="USER")
```

In `tests/test_agy.py`, add after `test_contract_runs_the_agy_binary_in_its_workdir`:

```python
@pytest.mark.parametrize("response", ["", None, "  \n"])
async def test_contract_raises_on_an_empty_answer(monkeypatch, fake_cli, response):
    _install_settings(monkeypatch)
    fake_cli("agy", _lines(_result(response=response)))

    with pytest.raises(CliHandlerError, match="AgyAIHandler: agy returned an empty answer$"):
        await AgyAIHandler().chat_completion(model="gemini-3.8-flash-high", system="SYS", user="USER")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --locked pytest -q tests/test_base.py tests/test_claude_code.py tests/test_codex.py tests/test_agy.py -k "empty_answer or surrounding_whitespace"`
Expected: every `empty_answer` test FAILS with `DID NOT RAISE <class 'pr_agent_cli_handlers.errors.CliHandlerError'>`. `test_an_answer_with_surrounding_whitespace_is_returned_unchanged` PASSES already; it pins that the fix does not strip the text.

- [ ] **Step 3: Implement**

In `src/pr_agent_cli_handlers/base.py`, inside `chat_completion`'s `try:` block, add after the `response.models` check (the `raise TypeError(f"parse_response returned models as ...")` line):

```python
            # An empty answer fails here, so PR-Agent's fallback loop runs instead of a later parse error that
            # names the wrong cause.
            if not response.text.strip():
                limit = " at the output limit" if response.finish_reason == "length" else ""
                raise CliHandlerError(f"{type(self).__name__}: {command.argv[0]} returned an empty answer{limit}")
```

The guard's `except CliHandlerError` branch redacts and re-raises it unchanged; do not add another `except`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --locked pytest -q tests/test_base.py tests/test_claude_code.py tests/test_codex.py tests/test_agy.py`
Expected: PASS.

- [ ] **Step 5: Update the spec**

In `docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md`:

1. Replace the R8 line with:
   `- **R8.** Every failure raises \`CliHandlerError\`: invalid configuration, launch (missing binary, permission, argument too long, NUL byte in an argument), timeout, non-zero exit, unparseable output and an empty answer (a successful run whose text is empty or only whitespace). PR-Agent's fallback loop then moves to the next model.`
2. In the agy re-gate list, delete the line `- a \`SUCCESS\` result with an empty response raises \`CliHandlerError\``; R8 now covers it for every adapter.

- [ ] **Step 6: Run the full gate**

Run: `uv lock --check && uv run --locked pytest -q && uv run --locked ruff check`
Expected: lock unchanged, all tests pass (one pre-existing PR-Agent Pydantic warning), `All checks passed!`.

- [ ] **Step 7: Commit**

```bash
git add src/pr_agent_cli_handlers/base.py tests/test_base.py tests/test_claude_code.py tests/test_codex.py tests/test_agy.py docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md && git commit -m "fix: raise CliHandlerError when a CLI returns an empty answer" -m "Closes #3" -- src/pr_agent_cli_handlers/base.py tests/test_base.py tests/test_claude_code.py tests/test_codex.py tests/test_agy.py docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md
```

- [ ] **Step 8 (amended 2026-10-17): Make `CliHandlerError` fallback-eligible**

1. Write `tests/test_errors.py` first: a test that runs PR-Agent's `retry_with_fallback_models` with `config.model` and one `config.fallback_models` entry set, and a callable that raises `CliHandlerError` for the first model and returns a value for the second, and asserts that the second model's value comes back. Restore any settings the test changes. Run it and confirm it fails because the `CliHandlerError` propagates.
2. In `src/pr_agent_cli_handlers/errors.py`, declare `class CliHandlerError(RuntimeError, FallbackEligibleError)`, importing `FallbackEligibleError` from `pr_agent.algo.token_budget`. Keep the module and class docstrings concise, imperative and true.
3. In `src/pr_agent_cli_handlers/base.py`, reword the Step 3 comment imperatively: `# Fail an empty answer here, so PR-Agent's fallback loop runs instead of a later parse error that names the wrong cause.`
4. In the spec's R8 line, replace `PR-Agent's fallback loop then moves to the next model.` with `` `CliHandlerError` subclasses PR-Agent's `FallbackEligibleError`, so PR-Agent's fallback loop then moves to the next model.``
5. Run the full gate: `uv lock --check && uv run --locked pytest -q && uv run --locked ruff check`.
6. Commit separately:

```bash
git add src/pr_agent_cli_handlers/errors.py src/pr_agent_cli_handlers/base.py tests/test_errors.py docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md && git commit -m "fix: let PR-Agent fall back to the next model on CliHandlerError" -- src/pr_agent_cli_handlers/errors.py src/pr_agent_cli_handlers/base.py tests/test_errors.py docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md
```

### Task 2: GitLab template fallback and CLI job settings in the README

**Files:**
- Modify: `templates/gitlab-ci.yml` (`variables`)
- Modify: `README.md` (Configuration section)
- Test: `tests/test_distribution.py`
- Modify: `docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md` (the "GitLab pipelines" bullet)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: the template job's `variables` contain `CONFIG__FALLBACK_MODELS: "[]"`; the README names `CONFIG__CUSTOM_MODEL_MAX_TOKENS`, `PR_AGENT_CLI_TIMEOUT=300` and `MAX_THINKING_TOKENS`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_distribution.py`, change the imports at the top to:

```python
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml
```

and add after `test_gitlab_template_runs_on_merge_request_pipelines`:

```python
def test_gitlab_template_passes_an_empty_fallback_list_to_pr_agent():
    job = yaml.safe_load((ROOT / "templates" / "gitlab-ci.yml").read_text())["pr-agent-cli-handlers"]
    env = {**os.environ, "LITELLM_LOCAL_MODEL_COST_MAP": "True",
           "CONFIG__FALLBACK_MODELS": job["variables"]["CONFIG__FALLBACK_MODELS"]}
    # PR-Agent splits a fallback value that is not a list on commas, so the string "[]" would become a model.
    script = ("from pr_agent.config_loader import get_settings; "
              "value = get_settings().config.fallback_models; print(isinstance(value, list), len(value))")

    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True)

    assert result.stdout.split()[-2:] == ["True", "0"]
```

and add after `test_readme_documents_every_environment_variable_and_handler`:

```python
def test_readme_documents_the_pr_agent_settings_a_cli_job_needs():
    readme = (ROOT / "README.md").read_text()
    for text in ("CONFIG__FALLBACK_MODELS", "CONFIG__CUSTOM_MODEL_MAX_TOKENS", "CONFIG__REASONING_EFFORT",
                 "PR_AGENT_CLI_TIMEOUT=300", "MAX_THINKING_TOKENS"):
        assert text in readme, text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --locked pytest -q tests/test_distribution.py -k "empty_fallback_list or settings_a_cli_job_needs"`
Expected: FAIL (`KeyError: 'CONFIG__FALLBACK_MODELS'`, and `AssertionError: CONFIG__CUSTOM_MODEL_MAX_TOKENS`).

- [ ] **Step 3: Set the template's fallback models**

In `templates/gitlab-ci.yml`, replace the `variables` block with:

```yaml
  variables:
    PR_AGENT_CLI_HANDLER: claude_code
    CONFIG__MODEL: claude-sonnet-5
    # PR-Agent's default fallback is an OpenAI model, which the claude_code handler rejects. List fallbacks the
    # selected CLI accepts, or none.
    CONFIG__FALLBACK_MODELS: "[]"
    CLI_VERSION: ""
    PACKAGE_VERSION: ""
```

- [ ] **Step 4: Document the CLI job settings**

In `README.md`, in the Configuration table, replace the `PR_AGENT_CLI_PASS_ENV` row with:

```markdown
| `PR_AGENT_CLI_PASS_ENV` | comma-separated names of extra environment variables to pass to the CLI, including the CLI's own switches | empty |
```

Then replace the paragraph that starts "The model, fallback models and reasoning effort come from PR-Agent's own settings" with:

```markdown
The model, fallback models and reasoning effort come from PR-Agent's own settings (`CONFIG__MODEL`,
`CONFIG__FALLBACK_MODELS`, `CONFIG__REASONING_EFFORT`).

- Fallback models must be models the selected CLI accepts. PR-Agent's default fallback is an OpenAI model, which
  the `claude_code` handler rejects, so set `CONFIG__FALLBACK_MODELS` to models the CLI accepts, or to `[]` for
  none. The GitLab template sets `[]`.
- A model PR-Agent does not know, such as the alias `opus`, needs `CONFIG__CUSTOM_MODEL_MAX_TOKENS` set to a
  positive token count, or PR-Agent refuses it.
- Set the effort with `CONFIG__REASONING_EFFORT`, not `--effort` in `PR_AGENT_CLI_EXTRA_ARGS`. When the CLI
  accepts the configured effort, which defaults to PR-Agent's `medium`, the handler passes it and names it in its
  log line, `AI response from <model> (effort <effort>)`, which PR-Agent prints to standard output. An effort in
  the extra arguments also reaches the CLI, after the handler's own, but the line still names the configured effort.
- PR-Agent's default `config.ai_timeout` is 120 seconds. A CLI call adds process start-up and reasoning time, so a
  large `improve` run can reach it and fail; `PR_AGENT_CLI_TIMEOUT=300` is a reasonable start.
- The CLI receives an allowlisted environment (see Security), which also drops the CLIs' own switches, such as
  `DISABLE_TELEMETRY`, `CLAUDE_CODE_MAX_OUTPUT_TOKENS` or `MAX_THINKING_TOKENS`. Name each one you set in
  `PR_AGENT_CLI_PASS_ENV`, or the CLI never sees it.
```

- [ ] **Step 5: Update the spec**

In `docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md`, in the "GitLab pipelines" bullet, replace `exactly as PR-Agent's own pipeline mode does.` with:

`exactly as PR-Agent's own pipeline mode does. It sets \`CONFIG__FALLBACK_MODELS\` to \`[]\`, since PR-Agent's default fallback is an OpenAI model that the default \`claude_code\` handler rejects.`

- [ ] **Step 6: Run the tests and the full gate**

Run: `uv run --locked pytest -q tests/test_distribution.py && uv lock --check && uv run --locked pytest -q && uv run --locked ruff check`
Expected: PASS, lock unchanged, `All checks passed!`.

- [ ] **Step 7: Commit**

```bash
git add templates/gitlab-ci.yml README.md tests/test_distribution.py docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md && git commit -m "fix: set no fallback model in the GitLab template and document CLI job settings" -m "Closes #1
Closes #2" -- templates/gitlab-ci.yml README.md tests/test_distribution.py docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md
```

## After the plan (not implementer tasks)

- Issue #9's re-gate list names "Raise on an empty `SUCCESS` response"; after Task 1 lands, the driver comments on #9 that R8 now covers it.
- Pushing closes #3, #1 and #2 through the commit messages; push only when the owner asks.
