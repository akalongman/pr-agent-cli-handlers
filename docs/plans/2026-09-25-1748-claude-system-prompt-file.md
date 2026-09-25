# Claude Code system prompt through a file Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pass PR-Agent's system prompt to Claude Code through a private file instead of a command-line argument, and log the model and effort each CLI call used.

**Architecture:** The base class gains a private-file helper and removes a command's temporary files after the call, whatever the outcome. The Claude Code adapter writes each call's system prompt to a new owner-only file in a second per-handler directory and passes `--system-prompt-file`. Commands carry the effort an adapter passed and responses carry the models the CLI reports, so the base can log both and file cost under the model that actually ran.

**Tech Stack:** Python 3.12, PR-Agent 0.46.0, pytest with pytest-asyncio (auto mode), uv 0.12.18, Claude Code 2.1.280 (pinned).

**Spec:** `docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md` (amended by Tasks 2 and 3), and GitHub issue #10.

## Background (facts the tasks rely on)

- Linux rejects a single argument over 131,072 bytes; `base.py` refuses any argument over 120,000 (R11). PR-Agent 0.46.0 renders `extra_instructions` into the system prompt, and a real repository's 72,055-byte rules file already puts the `review` system prompt near 85 KB.
- Claude Code 2.1.280 accepts `--system-prompt-file <path>` in `-p` mode together with `--restricted` and `--safe-mode`. Verified 2026-09-25: a 158,536-byte prompt file reached the model complete (a random code on its last line came back exactly). The CLI reads the file itself at startup, so `--restricted`'s file-tool confinement does not apply to it.
- PR-Agent constructs one handler per tool run and may run calls on it in parallel (`PRCodeSuggestions` uses `asyncio.gather`), so every call needs its own prompt file.
- Codex 0.156.1 has no instructions-file option for developer instructions; its only file key, `model_instructions_file`, replaces Codex's base instructions. The Codex adapter keeps passing `developer_instructions` in argv; this plan documents that limit and does not change it.
- Claude Code's JSON result reports the models it used as the keys of `modelUsage` (for example `{"claude-opus-5": {...}}`) and never reports the effort. PR-Agent's `record_ai_call(usage, model=..., cost_usd=...)` files a call's cost under `model` in `RunDetails.model_costs_usd`.
- Out of scope, decided 2026-09-25: a stable working-directory path for prompt-cache reuse. Claude Code puts the working directory in the first user message, but PR-Agent retries go through the same handler and so already share its directory; only identical prompts repeated across separate processes would gain, and a predictable path in a shared temporary directory adds risk.
- Consumer, decided 2026-09-25: the tsmulms MR review job will run on the Claude Code handler with a subscription. Task 3's log line `AI response from <model> (effort <effort>)` is what that job checks in place of pr-agent's LiteLLM thinking-configuration log lines, so keep its wording exactly as written.

## Global Constraints

- Python `>=3.12`. The only runtime dependency is `pr-agent>=0.46`, with no upper bound (R1).
- Environment variables, exactly: `PR_AGENT_CLI_HANDLER`, `PR_AGENT_CLI_BINARY`, `PR_AGENT_CLI_EXTRA_ARGS`, `PR_AGENT_CLI_TIMEOUT`, `PR_AGENT_CLI_PASS_ENV`. This plan adds none.
- Every handler failure raises `CliHandlerError` (R8). No command-line argument exceeds 120,000 bytes (R11).
- No automated test runs a real `claude`, `codex` or `agy` binary (R15).
- Ruff rules E, F, B, I at 120 columns; `uv run --locked ruff check` must be clean. Do not run `ruff format`.
- Comments and docstrings are concise and imperative. No em dashes or en dashes anywhere (code, docs, commit messages); hyphens keep their normal use.
- Commits: Conventional Commit titles, signed (never bypass signing), path-limited with `git add <paths> && git commit -m "<title>" -- <paths>`, no trailers, no mention of AI assistants. Never create or switch branches; never push.
- Run tests with `uv run --locked pytest -q <files>`; the gate is `uv lock --check`, `uv run --locked pytest -q` and `uv run --locked ruff check`. Local uv is 0.12.18.

## Review Focus

1. Parallel calls on one handler must each get their own prompt file and must not delete each other's. Pinned in Task 1 (`test_parallel_calls_write_and_remove_separate_files`) and Task 2 (`test_build_command_writes_a_new_prompt_file_per_call`).
2. A call that fails, times out, is cancelled or is refused for an oversized argument must still remove its prompt file. Pinned in Task 1 (`test_chat_completion_removes_temp_files_when_the_run_fails`, `..._when_the_call_is_cancelled`, `..._when_an_argument_is_too_long`).
3. A system prompt above 131,072 bytes must reach the CLI intact, with no argument over 120,000 bytes. Pinned in Task 2 (`test_contract_passes_a_system_prompt_larger_than_one_argument_allows`).
4. A system prompt that is not valid Unicode (a lone surrogate) must raise `CliHandlerError`, not `UnicodeEncodeError`, and leave no file behind. Pinned in Task 1 (`test_write_private_file_rejects_text_that_is_not_valid_unicode`).
5. A Claude Code result with no usable `modelUsage` object, or one naming a flag-like or brace-carrying model, must still parse and log. Pinned in Task 3 (`test_parse_response_reports_no_models_without_a_model_usage_object`, `test_parse_response_skips_model_names_outside_the_model_pattern`).

---

### Task 1: Private per-call files in the base

**Files:**
- Modify: `src/pr_agent_cli_handlers/base.py` (imports, `CliCommand`, new `write_private_file` and `_remove_temp_files`, `chat_completion`)
- Test: `tests/test_base.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `CliCommand.temp_files: list[str]` (default empty list); `CliAIHandler.write_private_file(directory: str, text: str, prefix: str) -> str` (static method; returns the new file's path; raises `CliHandlerError` when `text` cannot be encoded as UTF-8); `chat_completion` removes every path in `command.temp_files` after the run, on success and on every failure path.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_base.py` after `_install_settings`:

```python
class _FileAdapter(_EchoAdapter):
    """Write the system prompt to a private file, as the Claude Code adapter does."""

    def __init__(self, directory):
        super().__init__()
        self.directory = directory
        self.written = []

    def build_command(self, model, system, user):
        path = self.write_private_file(self.directory, system, "system-prompt-")
        self.written.append(path)
        return CliCommand(argv=[self.binary, "--system-prompt-file", path], stdin=user, temp_files=[path])


def test_write_private_file_creates_an_owner_only_file_with_the_text(tmp_path):
    path = CliAIHandler.write_private_file(str(tmp_path), "héllo\nworld", "system-prompt-")

    assert os.path.dirname(path) == str(tmp_path)
    assert os.path.basename(path).startswith("system-prompt-")
    with open(path, encoding="utf-8") as handle:
        assert handle.read() == "héllo\nworld"
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_write_private_file_uses_a_new_name_per_call(tmp_path):
    first = CliAIHandler.write_private_file(str(tmp_path), "a", "system-prompt-")
    second = CliAIHandler.write_private_file(str(tmp_path), "a", "system-prompt-")
    assert first != second


def test_write_private_file_rejects_text_that_is_not_valid_unicode(tmp_path):
    with pytest.raises(CliHandlerError, match="UTF-8"):
        CliAIHandler.write_private_file(str(tmp_path), "bad \ud800 surrogate", "system-prompt-")
    assert os.listdir(tmp_path) == []


async def test_chat_completion_removes_the_command_temp_files_after_the_run(monkeypatch, tmp_path):
    _install_settings(monkeypatch)
    handler = _FileAdapter(str(tmp_path))
    seen = {}

    async def run(command):
        with open(command.argv[2], encoding="utf-8") as handle:
            seen["content"] = handle.read()
        return "ok"

    handler._run = run

    await handler.chat_completion(model="m", system="SYS", user="u")

    assert seen["content"] == "SYS"
    assert os.listdir(tmp_path) == []


async def test_chat_completion_removes_temp_files_when_the_run_fails(monkeypatch, tmp_path):
    _install_settings(monkeypatch)
    handler = _FileAdapter(str(tmp_path))

    async def run(command):
        raise CliHandlerError("boom")

    handler._run = run

    with pytest.raises(CliHandlerError, match="boom"):
        await handler.chat_completion(model="m", system="SYS", user="u")
    assert os.listdir(tmp_path) == []


async def test_chat_completion_removes_temp_files_when_an_argument_is_too_long(monkeypatch, tmp_path):
    _install_settings(monkeypatch)

    class _LongArgAdapter(_FileAdapter):
        def build_command(self, model, system, user):
            command = super().build_command(model, system, user)
            command.argv.append("x" * (MAX_ARGV_ELEMENT_BYTES + 1))
            return command

    handler = _LongArgAdapter(str(tmp_path))

    with pytest.raises(CliHandlerError, match="exceeds"):
        await handler.chat_completion(model="m", system="SYS", user="u")
    assert os.listdir(tmp_path) == []


async def test_chat_completion_removes_temp_files_when_the_call_is_cancelled(monkeypatch, tmp_path):
    _install_settings(monkeypatch)
    handler = _FileAdapter(str(tmp_path))
    started = asyncio.Event()

    async def run(command):
        started.set()
        await asyncio.sleep(3600)

    handler._run = run

    task = asyncio.create_task(handler.chat_completion(model="m", system="SYS", user="u"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert os.listdir(tmp_path) == []


async def test_parallel_calls_write_and_remove_separate_files(monkeypatch, tmp_path):
    _install_settings(monkeypatch)
    handler = _FileAdapter(str(tmp_path))
    contents = []

    async def run(command):
        await asyncio.sleep(0.01)
        with open(command.argv[2], encoding="utf-8") as handle:
            contents.append(handle.read())
        return "ok"

    handler._run = run

    await asyncio.gather(*(handler.chat_completion(model="m", system=f"SYS{i}", user="u") for i in range(5)))

    assert sorted(contents) == [f"SYS{i}" for i in range(5)]
    assert len(set(handler.written)) == 5
    assert os.listdir(tmp_path) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --locked pytest -q tests/test_base.py -k "write_private_file or temp_files or parallel_calls"`
Expected: FAIL (`CliCommand.__init__() got an unexpected keyword argument 'temp_files'` and `CliAIHandler has no attribute 'write_private_file'`).

- [ ] **Step 3: Implement**

In `src/pr_agent_cli_handlers/base.py`, change the dataclass import to `from dataclasses import dataclass, field` and give `CliCommand` the new field:

```python
@dataclass
class CliCommand:
    argv: list[str]
    stdin: Optional[str] = None
    cwd: Optional[str] = None
    # Remove these files once the call ends, whatever its outcome.
    temp_files: list[str] = field(default_factory=list)
```

Add these two methods to `CliAIHandler`, after `create_workdir`:

```python
    @staticmethod
    def write_private_file(directory: str, text: str, prefix: str) -> str:
        """Write ``text`` to a new file in ``directory`` that only this user can read, and return its path.

        Use a new name per call: parallel calls on one handler share its directories.
        """
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=".txt", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
        except UnicodeEncodeError as e:
            with suppress(FileNotFoundError):
                os.remove(path)
            raise CliHandlerError(f"cannot write the prompt as UTF-8: {e.reason}") from e
        except BaseException:
            with suppress(FileNotFoundError):
                os.remove(path)
            raise
        return path

    @staticmethod
    def _remove_temp_files(command: CliCommand) -> None:
        for path in command.temp_files:
            with suppress(FileNotFoundError):
                os.remove(path)
```

In `chat_completion`, wrap the argument check and the run so the files go whatever happens. Replace the block from `command = self.build_command(...)` through `stdout = await self._run(command)` with:

```python
        command = self.build_command(mapped_model, system, user)
        try:
            for arg in command.argv:
                if len(arg.encode("utf-8")) > MAX_ARGV_ELEMENT_BYTES:
                    raise CliHandlerError(
                        f"{type(self).__name__}: a command argument exceeds {MAX_ARGV_ELEMENT_BYTES} bytes; "
                        "the prompt does not fit in one argv element")
            get_logger().debug("Prompts", artifact={"system": system, "user": user})
            stdout = await self._run(command)
        finally:
            self._remove_temp_files(command)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --locked pytest -q tests/test_base.py`
Expected: PASS, including every existing base test.

- [ ] **Step 5: Commit**

```bash
git add src/pr_agent_cli_handlers/base.py tests/test_base.py && git commit -m "feat: let adapters pass private per-call files to the CLI" -- src/pr_agent_cli_handlers/base.py tests/test_base.py
```

### Task 2: Claude Code reads its system prompt from a file

**Files:**
- Modify: `src/pr_agent_cli_handlers/claude_code.py` (module docstring, `__init__`, `build_command`)
- Modify: `tests/conftest.py` (`fake_cli` records the system prompt file's content)
- Test: `tests/test_claude_code.py`
- Modify: `docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md` (R11, the Claude Code argv block and bullets)
- Modify: `README.md` (Security, Limitations), `CHANGELOG.md` (0.1.0)

**Interfaces:**
- Consumes: `CliCommand.temp_files`, `CliAIHandler.write_private_file(directory, text, prefix)` from Task 1.
- Produces: `ClaudeCodeAIHandler.prompt_dir: str` (a private per-handler directory, separate from `workdir`); `build_command` returns argv with `--system-prompt-file <path>` in place of `--system-prompt <text>`, and `temp_files=[<path>]`.

- [ ] **Step 1: Teach the fake CLI to record the prompt file**

In `tests/conftest.py`, inside `fake_cli`'s generated script, record the content of the file that follows `--system-prompt-file` while it still exists. Replace the script's `data = ...` line with these four lines:

```python
            "data = {'argv': sys.argv[1:], 'stdin': sys.stdin.read(), 'cwd': os.getcwd()}\n"
            "if '--system-prompt-file' in sys.argv:\n"
            "    path = sys.argv[sys.argv.index('--system-prompt-file') + 1]\n"
            "    data['system_prompt'] = open(path, encoding='utf-8').read()\n"
```

- [ ] **Step 2: Write the failing tests**

In `tests/test_claude_code.py`, replace `test_build_command_uses_the_restricted_headless_flag_set`, `test_build_command_runs_in_one_empty_workdir_per_handler` and `test_contract_runs_the_claude_binary_with_the_built_command` with the versions below, and add the other tests:

```python
def test_build_command_uses_the_restricted_headless_flag_set(monkeypatch):
    _install_settings(monkeypatch, {"CONFIG.REASONING_EFFORT": "xhigh"})
    monkeypatch.setenv("PR_AGENT_CLI_EXTRA_ARGS", "--verbose")
    handler = ClaudeCodeAIHandler()
    command = handler.build_command("claude-opus-5", "SYS", "USER")
    prompt_file = command.argv[command.argv.index("--system-prompt-file") + 1]

    assert command.argv == [
        "claude", "-p", "--restricted", "--safe-mode", "--strict-mcp-config", "--tools", "",
        "--no-session-persistence", "--output-format", "json", "--system-prompt-file", prompt_file,
        "--model", "claude-opus-5", "--effort", "xhigh", "--verbose",
    ]
    assert command.stdin == "USER"
    assert command.temp_files == [prompt_file]
    assert "SYS" not in command.argv
    assert os.path.dirname(prompt_file) == handler.prompt_dir
    with open(prompt_file, encoding="utf-8") as handle:
        assert handle.read() == "SYS"


def test_build_command_runs_in_one_empty_workdir_per_handler(monkeypatch):
    _install_settings(monkeypatch)
    handler = ClaudeCodeAIHandler()

    first = handler.build_command("claude-opus-5", "SYS", "USER")
    second = handler.build_command("claude-opus-5", "SYS", "USER")

    assert first.cwd == second.cwd == handler.workdir
    assert handler.prompt_dir != handler.workdir
    assert os.path.isdir(handler.workdir)
    assert os.listdir(handler.workdir) == []


def test_build_command_writes_a_new_prompt_file_per_call(monkeypatch):
    _install_settings(monkeypatch)
    handler = ClaudeCodeAIHandler()

    first = handler.build_command("claude-opus-5", "ONE", "USER").temp_files
    second = handler.build_command("claude-opus-5", "TWO", "USER").temp_files

    assert first != second
    assert sorted(os.listdir(handler.prompt_dir)) == sorted(os.path.basename(p) for p in first + second)


def test_prompt_dir_is_readable_by_its_owner_only(monkeypatch):
    _install_settings(monkeypatch)
    handler = ClaudeCodeAIHandler()
    assert os.stat(handler.prompt_dir).st_mode & 0o777 == 0o700


async def test_contract_runs_the_claude_binary_with_the_built_command(monkeypatch, fake_cli):
    _install_settings(monkeypatch)
    record = fake_cli("claude", _success_payload(result="looks good"))
    handler = ClaudeCodeAIHandler()

    text, finish_reason = await handler.chat_completion(model="anthropic/claude-opus-5", system="SYS", user="USER")

    recorded = json.loads(record.read_text())
    prompt_file = recorded["argv"][recorded["argv"].index("--system-prompt-file") + 1]
    assert (text, finish_reason) == ("looks good", "stop")
    assert os.path.dirname(prompt_file) == handler.prompt_dir
    assert recorded["system_prompt"] == "SYS"
    assert "SYS" not in recorded["argv"]
    assert recorded["stdin"] == "USER"
    assert recorded["cwd"] == handler.workdir
    assert recorded["cwd"] != os.getcwd()
    assert os.listdir(handler.prompt_dir) == []


async def test_contract_passes_a_system_prompt_larger_than_one_argument_allows(monkeypatch, fake_cli):
    _install_settings(monkeypatch)
    record = fake_cli("claude", _success_payload(result="ok"))
    # 200,000 bytes, above Linux's 131,072-byte limit for one argument.
    system = "rule line\n" * 20_000
    handler = ClaudeCodeAIHandler()

    await handler.chat_completion(model="claude-opus-5", system=system, user="USER")

    recorded = json.loads(record.read_text())
    assert recorded["system_prompt"] == system
    assert all(len(arg.encode("utf-8")) <= cli_module.MAX_ARGV_ELEMENT_BYTES for arg in recorded["argv"])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --locked pytest -q tests/test_claude_code.py`
Expected: FAIL (`--system-prompt-file` is not in the argv, and `ClaudeCodeAIHandler` has no `prompt_dir`).

- [ ] **Step 4: Implement**

In `src/pr_agent_cli_handlers/claude_code.py`, replace the whole module docstring (today it names ``--system-prompt``) with:

```python
"""Run Claude Code headless (``claude -p``) once per call, in an empty working directory.

Turn the harness into a plain completion: ``--system-prompt-file`` replaces its own system prompt with
PR-Agent's, read from a file only this user can read, ``--tools ""`` and ``--strict-mcp-config`` leave no
tools and no MCP servers, ``--restricted`` skips settings files, ``--safe-mode`` skips CLAUDE.md and other
customizations (skills, plugins, hooks), and ``--no-session-persistence`` keeps nothing. A file, unlike an
argument, has no 128 KiB limit and does not show in the process list. The empty directory leaves no project
CLAUDE.md to find, and ``DISABLE_AUTOUPDATER=1`` keeps the installed version for every call. Authentication is
the harness's own login; this adapter reads no credentials.
"""
```

Then replace `__init__` and `build_command`:

```python
    def __init__(self):
        super().__init__()
        self.workdir = self.create_workdir("pr-agent-claude-")
        # Keep prompt files out of the working directory, so the CLI still starts in an empty one.
        self.prompt_dir = self.create_workdir("pr-agent-claude-prompt-")

    def build_command(self, model: str, system: str, user: str) -> CliCommand:
        prompt_file = self.write_private_file(self.prompt_dir, system, "system-prompt-")
        argv = [
            self.binary, "-p",
            "--restricted", "--safe-mode", "--strict-mcp-config", "--tools", "",
            "--no-session-persistence", "--output-format", "json",
            "--system-prompt-file", prompt_file, "--model", model,
        ]
        effort = self.reasoning_effort()
        if effort in CLAUDE_CODE_EFFORTS:
            argv += ["--effort", effort]
        argv += self.extra_args
        return CliCommand(argv=argv, stdin=user, cwd=self.workdir, temp_files=[prompt_file])
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --locked pytest -q tests/test_claude_code.py tests/test_base.py`
Expected: PASS.

- [ ] **Step 6: Update the spec, README and changelog**

In `docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md`:

1. Replace the R11 line with:
   `- **R11.** No command-line argument exceeds 120,000 bytes. Adapters pass the user prompt on standard input, and the Claude Code adapter passes the system prompt through a file. The Codex adapter's system prompt still travels in argv as \`developer_instructions\` and is bounded by this limit.`
2. In the Claude Code argv block, replace `--output-format json --system-prompt <system> --model <model>` with `--output-format json --system-prompt-file <file> --model <model>`.
3. After the Claude Code "Working directory" bullet, add:
   `- **System prompt:** written to a new file that only the user can read, in a second private per-handler directory outside the working directory, passed with \`--system-prompt-file\`, and removed when the call ends. A long prompt is then not bounded by R11 and does not show in the process list. Verified on 2.1.280 with a 158,536-byte prompt whose last line reached the model (2026-09-25).`

In `README.md`, add to the Security list, after the tools bullet:

```markdown
- Claude Code reads PR-Agent's system prompt from a file only you can read, removed after each call, so it does not
  appear in the process list. Codex still receives it as a command-line argument.
```

and add to the Limitations list:

```markdown
- With the Codex handler, PR-Agent's system prompt (including `extra_instructions`) must stay under about
  120,000 bytes, because it travels as one command-line argument.
```

In `CHANGELOG.md`, under `## 0.1.0 (unreleased)`, add:

```markdown
- Pass Claude Code's system prompt through a private file, so long instructions fit and stay out of the process list.
```

- [ ] **Step 7: Run the full gate**

Run: `uv run --locked pytest -q && uv run --locked ruff check`
Expected: all tests pass (the one pre-existing PR-Agent Pydantic warning is expected) and `All checks passed!`.

- [ ] **Step 8: Commit**

```bash
git add src/pr_agent_cli_handlers/claude_code.py tests/conftest.py tests/test_claude_code.py docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md README.md CHANGELOG.md && git commit -m "feat: pass Claude Code's system prompt through a private file" -- src/pr_agent_cli_handlers/claude_code.py tests/conftest.py tests/test_claude_code.py docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md README.md CHANGELOG.md
```

### Task 3: Log the model and effort each call used

**Files:**
- Modify: `src/pr_agent_cli_handlers/base.py` (`CliCommand`, `CliResponse`, `chat_completion`'s info log and `record_ai_call`)
- Modify: `src/pr_agent_cli_handlers/claude_code.py` (`build_command` sets `effort`, `parse_response` reads `modelUsage`)
- Modify: `src/pr_agent_cli_handlers/codex.py` (`build_command` sets `effort`)
- Test: `tests/test_base.py`, `tests/test_claude_code.py`, `tests/test_codex.py`
- Modify: `docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md` (R13, R14), `CHANGELOG.md`

**Interfaces:**
- Consumes: Task 2's `ClaudeCodeAIHandler.build_command` (the version with `--system-prompt-file` and `temp_files`).
- Produces: `CliCommand.effort: Optional[str]` (the effort the adapter passed, or `None`); `CliResponse.models: tuple[str, ...]` (models the CLI reports, default `()`); the info log line `AI response from <model> (effort <effort or default>): <n> prompt tokens, <m> completion tokens` with fields `model`, `models_used`, `effort`; `record_ai_call` receives the single reported model when the CLI reports exactly one, else the requested (mapped) model.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_base.py`:

```python
class _ModelReportingAdapter(_EchoAdapter):
    def __init__(self, models=("real-model-1",)):
        super().__init__()
        self.models = models

    def build_command(self, model, system, user):
        command = super().build_command(model, system, user)
        command.effort = "high"
        return command

    def parse_response(self, stdout):
        return CliResponse(text="ok", prompt_tokens=7, completion_tokens=3, cost_usd=0.5, models=self.models)


async def test_chat_completion_logs_the_reported_model_and_effort(monkeypatch):
    _install_settings(monkeypatch)
    infos = []
    monkeypatch.setattr(cli_module, "get_logger", lambda: SimpleNamespace(
        info=lambda msg, **kw: infos.append((msg, kw)), warning=lambda *a, **kw: None, debug=lambda *a, **kw: None))

    await _ModelReportingAdapter().chat_completion(model="anthropic/claude-opus-5", system="s", user="u")

    message, fields = infos[-1]
    assert message == "AI response from real-model-1 (effort high): 7 prompt tokens, 3 completion tokens"
    assert fields["model"] == "claude-opus-5"
    assert fields["models_used"] == ["real-model-1"]
    assert fields["effort"] == "high"


async def test_chat_completion_logs_the_requested_model_and_default_effort_without_reports(monkeypatch):
    _install_settings(monkeypatch)
    infos = []
    monkeypatch.setattr(cli_module, "get_logger", lambda: SimpleNamespace(
        info=lambda msg, **kw: infos.append((msg, kw)), warning=lambda *a, **kw: None, debug=lambda *a, **kw: None))

    await _EchoAdapter().chat_completion(model="anthropic/claude-opus-5", system="s", user="u")

    message, fields = infos[-1]
    assert message == "AI response from claude-opus-5 (effort default): 7 prompt tokens, 3 completion tokens"
    assert fields["models_used"] == []
    assert fields["effort"] is None


async def test_chat_completion_records_cost_under_the_single_reported_model(monkeypatch):
    _install_settings(monkeypatch)
    init_run_details()

    await _ModelReportingAdapter().chat_completion(model="anthropic/claude-opus-5", system="s", user="u")

    assert list(get_run_details().model_costs_usd) == ["real-model-1"]


@pytest.mark.parametrize("models", [(), ("model-a", "model-b")])
async def test_chat_completion_records_cost_under_the_requested_model_otherwise(monkeypatch, models):
    _install_settings(monkeypatch)
    init_run_details()

    await _ModelReportingAdapter(models=models).chat_completion(model="anthropic/claude-opus-5", system="s", user="u")

    assert list(get_run_details().model_costs_usd) == ["claude-opus-5"]
```

Add to `tests/test_claude_code.py`:

```python
def test_parse_response_reads_the_models_the_cli_reports(monkeypatch):
    _install_settings(monkeypatch)
    payload = _success_payload(modelUsage={"claude-opus-5": {"inputTokens": 2, "outputTokens": 30}})
    assert ClaudeCodeAIHandler().parse_response(payload).models == ("claude-opus-5",)


@pytest.mark.parametrize("model_usage", [[], "claude-opus-5", None])
def test_parse_response_reports_no_models_without_a_model_usage_object(monkeypatch, model_usage):
    _install_settings(monkeypatch)
    payload = _success_payload(modelUsage=model_usage)
    assert ClaudeCodeAIHandler().parse_response(payload).models == ()


def test_parse_response_skips_model_names_outside_the_model_pattern(monkeypatch):
    _install_settings(monkeypatch)
    payload = _success_payload(modelUsage={"--flag": {}, "a{b}": {}, "claude-sonnet-5": {}})
    assert ClaudeCodeAIHandler().parse_response(payload).models == ("claude-sonnet-5",)


@pytest.mark.parametrize("configured, passed", [("xhigh", "xhigh"), ("minimal", None), ("", None)])
def test_build_command_reports_the_effort_it_passes(monkeypatch, configured, passed):
    _install_settings(monkeypatch, {"CONFIG.REASONING_EFFORT": configured})
    assert ClaudeCodeAIHandler().build_command("claude-opus-5", "SYS", "USER").effort == passed
```

Add to `tests/test_codex.py` (use the file's own `_install_settings` helper):

```python
@pytest.mark.parametrize("configured, passed", [("minimal", "low"), ("high", "high"), ("turbo", None)])
def test_build_command_reports_the_effort_it_passes(monkeypatch, configured, passed):
    _install_settings(monkeypatch, {"CONFIG.REASONING_EFFORT": configured})
    assert CodexAIHandler().build_command("gpt-6", "SYS", "USER").effort == passed
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --locked pytest -q tests/test_base.py tests/test_claude_code.py tests/test_codex.py -k "reported or reports or effort_it_passes or requested_model or model_pattern"`
Expected: FAIL (`CliResponse` has no `models` field; `CliCommand` has no `effort` field).

- [ ] **Step 3: Implement the base**

In `src/pr_agent_cli_handlers/base.py`, add the fields:

```python
@dataclass
class CliCommand:
    argv: list[str]
    stdin: Optional[str] = None
    cwd: Optional[str] = None
    # Remove these files once the call ends, whatever its outcome.
    temp_files: list[str] = field(default_factory=list)
    # The reasoning effort the adapter passed to the CLI, or None when it passed none.
    effort: Optional[str] = None


@dataclass
class CliResponse:
    text: str
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Optional[float] = None
    # The models the CLI reports it used, when it reports them.
    models: tuple[str, ...] = ()
```

In `chat_completion`, replace the `get_logger().info("AI response", ...)` call and the `record_ai_call(...)` line with:

```python
        # Prefer the model the CLI reports: an alias such as ``opus`` resolves to a concrete model there.
        reported_model = response.models[0] if len(response.models) == 1 else mapped_model
        get_logger().info(
            f"AI response from {reported_model} (effort {command.effort or 'default'}): "
            f"{response.prompt_tokens} prompt tokens, {response.completion_tokens} completion tokens",
            response=response.text, finish_reason=response.finish_reason, model=mapped_model,
            models_used=list(response.models), effort=command.effort,
            prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens)
```

and, keeping the `usage` dict as it is:

```python
        record_ai_call(usage, model=reported_model, cost_usd=response.cost_usd)
```

- [ ] **Step 4: Implement the adapters**

In `src/pr_agent_cli_handlers/claude_code.py`, change the effort part of `build_command` and its return:

```python
        effort = self.reasoning_effort()
        passed_effort = effort if effort in CLAUDE_CODE_EFFORTS else None
        if passed_effort:
            argv += ["--effort", passed_effort]
        argv += self.extra_args
        return CliCommand(argv=argv, stdin=user, cwd=self.workdir, temp_files=[prompt_file], effort=passed_effort)
```

In `parse_response`, before the final `return`, read the reported models, keeping only names that match `MODEL_NAME` (already imported from `base`):

```python
        model_usage = data.get("modelUsage")
        models = tuple(
            name for name in model_usage if isinstance(name, str) and MODEL_NAME.fullmatch(name)
        ) if isinstance(model_usage, dict) else ()
```

and pass `models=models` in the returned `CliResponse(...)`.

In `src/pr_agent_cli_handlers/codex.py`, change the effort part of `build_command` and its return:

```python
        effort = self.reasoning_effort()
        effort = CODEX_EFFORT_ALIASES.get(effort, effort)
        passed_effort = effort if effort in CODEX_EFFORTS else None
        if passed_effort:
            argv += ["--config", f'model_reasoning_effort="{passed_effort}"']
```

and at the end:

```python
        return CliCommand(argv=argv, stdin=user, effort=passed_effort)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --locked pytest -q tests/test_base.py tests/test_claude_code.py tests/test_codex.py`
Expected: PASS.

- [ ] **Step 6: Update the spec and changelog**

In `docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md`, replace R13 and R14 with:

```markdown
- **R13.** Prompts are logged at debug level (`get_logger().debug("Prompts", artifact={...})`, PR-Agent's own idiom), and the response at info level with a message naming the model the CLI reports (or the requested one) and the effort the adapter passed. No credential is ever logged.
- **R14.** Each successful call is recorded with PR-Agent's `record_ai_call`, with token counts and cost when the CLI reports them, under the model the CLI reports when it reports exactly one, else the requested model.
```

In `CHANGELOG.md`, under `## 0.1.0 (unreleased)`, add:

```markdown
- Log the model and reasoning effort of each CLI call, and file its cost under the model the CLI reports.
```

- [ ] **Step 7: Run the full gate**

Run: `uv lock --check && uv run --locked pytest -q && uv run --locked ruff check`
Expected: lock unchanged, all tests pass (one pre-existing PR-Agent warning), `All checks passed!`.

- [ ] **Step 8: Commit**

```bash
git add src/pr_agent_cli_handlers/base.py src/pr_agent_cli_handlers/claude_code.py src/pr_agent_cli_handlers/codex.py tests/test_base.py tests/test_claude_code.py tests/test_codex.py docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md CHANGELOG.md && git commit -m "feat: log the model and effort of each CLI call" -- src/pr_agent_cli_handlers/base.py src/pr_agent_cli_handlers/claude_code.py src/pr_agent_cli_handlers/codex.py tests/test_base.py tests/test_claude_code.py tests/test_codex.py docs/specs/2026-09-23-1630-pr-agent-cli-handlers-design.md CHANGELOG.md
```

## After the plan (not implementer tasks)

- The owner runs `scripts/smoke claude_code` once against the pinned CLI before tagging the release that carries this change (R15 keeps live runs out of pytest).
- Release route, decided 2026-09-25: make the repository public and publish to PyPI through `release.yml` (PyPI pending publisher and a protected `pypi` environment first). Before the repository goes public, decide whether to replace the four `/home/longman/...` paths in `docs/plans/2026-09-23-1649-pr-agent-cli-handlers.md`.
- Close GitHub issue #10 with the commit list; the Codex half stays documented as a limitation. Evaluating Codex's `model_instructions_file` (it replaces the base instructions, a behavior change that needs its own live check) is a separate issue.
