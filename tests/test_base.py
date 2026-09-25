import asyncio
import errno
import gc
import json
import os
import sys
import time
from types import SimpleNamespace

import pytest
from pr_agent.algo.run_details import get_run_details, init_run_details

import pr_agent_cli_handlers.base as cli_module
from pr_agent_cli_handlers.base import MAX_ARGV_ELEMENT_BYTES, CliAIHandler, CliCommand, CliResponse
from pr_agent_cli_handlers.errors import CliHandlerError


class _FakeSettings:
    def __init__(self, values=None, ai_timeout=30):
        self.values = values or {}
        self.config = SimpleNamespace(ai_timeout=ai_timeout)

    def get(self, key, default=None):
        return self.values.get(key, default)


class _EchoAdapter(CliAIHandler):
    default_binary = "echo-bin"
    credential_env = frozenset({"ECHO_API_KEY"})

    def __init__(self):
        super().__init__()
        self.seen_command = None
        self.canned_stdout = "canned"

    def build_command(self, model, system, user):
        return CliCommand(argv=[self.binary, "--model", model, "--system", system, *self.extra_args], stdin=user)

    def parse_response(self, stdout):
        return CliResponse(text=stdout.upper(), finish_reason="stop", prompt_tokens=7, completion_tokens=3,
                           cost_usd=0.5)

    async def _run(self, command):
        self.seen_command = command
        return self.canned_stdout


def _install_settings(monkeypatch, values=None, ai_timeout=30):
    monkeypatch.setattr(cli_module, "get_settings", lambda: _FakeSettings(values, ai_timeout))


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


def test_write_private_file_writes_line_endings_unchanged(monkeypatch, tmp_path):
    real_fdopen = os.fdopen

    def windows_fdopen(fd, *args, newline=None, **kwargs):
        """Translate "\\n" to "\\r\\n" unless the caller sets ``newline``, as text mode does on Windows."""
        return real_fdopen(fd, *args, newline="\r\n" if newline is None else newline, **kwargs)

    monkeypatch.setattr(os, "fdopen", windows_fdopen)

    path = CliAIHandler.write_private_file(str(tmp_path), "one\ntwo\r\n", "system-prompt-")

    with open(path, "rb") as handle:
        assert handle.read() == b"one\ntwo\r\n"


def test_write_private_file_uses_a_new_name_per_call(tmp_path):
    first = CliAIHandler.write_private_file(str(tmp_path), "a", "system-prompt-")
    second = CliAIHandler.write_private_file(str(tmp_path), "a", "system-prompt-")
    assert first != second


def test_write_private_file_rejects_text_that_is_not_valid_unicode(tmp_path):
    with pytest.raises(CliHandlerError, match="UTF-8"):
        CliAIHandler.write_private_file(str(tmp_path), "bad \ud800 surrogate", "system-prompt-")
    assert os.listdir(tmp_path) == []


def test_write_private_file_raises_when_the_directory_is_missing(tmp_path):
    missing = tmp_path / "gone"

    with pytest.raises(CliHandlerError, match="gone") as exc_info:
        CliAIHandler.write_private_file(str(missing), "a", "system-prompt-")
    assert isinstance(exc_info.value.__cause__, FileNotFoundError)


def test_write_private_file_removes_the_file_when_the_write_fails(monkeypatch, tmp_path):
    real_fdopen = os.fdopen

    class _FullDisk:
        """Open the real file, then fail every write as a full disk does."""

        def __init__(self, fd, *args, **kwargs):
            self.handle = real_fdopen(fd, *args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            self.handle.close()

        def write(self, text):
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(cli_module.os, "fdopen", _FullDisk)

    with pytest.raises(CliHandlerError, match=os.strerror(errno.ENOSPC)) as exc_info:
        CliAIHandler.write_private_file(str(tmp_path), "a", "system-prompt-")
    assert exc_info.value.__cause__.errno == errno.ENOSPC
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
    # Bound the wait: if the call fails before it runs, the event never fires and the test would hang.
    await asyncio.wait_for(started.wait(), timeout=5)
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


def _fail_to_remove(monkeypatch, handler):
    """Make removing the handler's written files fail with PermissionError, and collect the logged warnings."""
    warnings = []
    monkeypatch.setattr(cli_module, "get_logger", lambda: SimpleNamespace(
        warning=lambda msg, **kw: warnings.append(msg), info=lambda *a, **kw: None, debug=lambda *a, **kw: None))
    real_remove = os.remove

    def remove(path):
        if path in handler.written:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), path)
        real_remove(path)

    monkeypatch.setattr(cli_module.os, "remove", remove)
    return warnings


async def test_a_temp_file_that_cannot_be_removed_does_not_change_the_result(monkeypatch, tmp_path):
    _install_settings(monkeypatch)
    handler = _FileAdapter(str(tmp_path))
    warnings = _fail_to_remove(monkeypatch, handler)

    response = await handler.chat_completion(model="m", system="SYS", user="u")

    assert response == ("CANNED", "stop")
    assert len(warnings) == 1
    assert handler.written[0] in warnings[0]
    assert os.strerror(errno.EACCES) in warnings[0]


async def test_a_temp_file_that_cannot_be_removed_does_not_replace_the_run_error(monkeypatch, tmp_path):
    _install_settings(monkeypatch)
    handler = _FileAdapter(str(tmp_path))
    warnings = _fail_to_remove(monkeypatch, handler)
    raised = CliHandlerError("boom")

    async def run(command):
        raise raised

    handler._run = run

    with pytest.raises(CliHandlerError) as exc_info:
        await handler.chat_completion(model="m", system="SYS", user="u")
    assert exc_info.value is raised
    assert len(warnings) == 1


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


def test_defaults_fall_back_to_class_binary_and_config_timeout(monkeypatch):
    _install_settings(monkeypatch, {}, ai_timeout=42)
    handler = _EchoAdapter()
    assert handler.binary == "echo-bin"
    assert handler.extra_args == []
    assert handler.timeout == 42.0


@pytest.mark.parametrize("ai_timeout", [None, "soon"], ids=["none", "word"])
def test_invalid_config_ai_timeout_raises_naming_the_setting(monkeypatch, ai_timeout):
    _install_settings(monkeypatch, ai_timeout=ai_timeout)

    with pytest.raises(CliHandlerError, match=r"config\.ai_timeout"):
        _EchoAdapter()


async def test_chat_completion_runs_command_and_records_usage(monkeypatch):
    _install_settings(monkeypatch)
    init_run_details()
    handler = _EchoAdapter()

    response = await handler.chat_completion(model="anthropic/claude-opus-5", system="sys", user="usr")

    assert response == ("CANNED", "stop")
    assert handler.seen_command.argv == ["echo-bin", "--model", "claude-opus-5", "--system", "sys"]
    assert handler.seen_command.stdin == "usr"
    details = get_run_details()
    assert details.num_ai_calls == 1
    assert details.prompt_tokens == 7
    assert details.completion_tokens == 3
    assert details.total_tokens == 10


async def test_image_path_is_ignored_with_a_warning(monkeypatch):
    _install_settings(monkeypatch)
    warnings = []
    monkeypatch.setattr(cli_module, "get_logger", lambda: SimpleNamespace(
        warning=lambda msg, **kw: warnings.append(msg), info=lambda *a, **kw: None, debug=lambda *a, **kw: None))
    handler = _EchoAdapter()

    await handler.chat_completion(model="m", system="s", user="u", img_path="/tmp/x.png")

    assert any("Ignoring image path" in message for message in warnings)


async def test_chat_completion_logs_the_prompts_as_a_debug_artifact(monkeypatch):
    _install_settings(monkeypatch)
    debug_calls = []
    monkeypatch.setattr(cli_module, "get_logger", lambda: SimpleNamespace(
        debug=lambda msg, **kw: debug_calls.append((msg, kw)), info=lambda *a, **kw: None))

    await _EchoAdapter().chat_completion(model="m", system="sys", user="usr")

    assert debug_calls == [("Prompts", {"artifact": {"system": "sys", "user": "usr"}})]


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


async def test_oversized_argv_element_raises_before_running(monkeypatch):
    _install_settings(monkeypatch)
    handler = _EchoAdapter()

    with pytest.raises(CliHandlerError):
        await handler.chat_completion(model="m", system="x" * (MAX_ARGV_ELEMENT_BYTES + 1), user="u")
    assert handler.seen_command is None


class _BrokenParserAdapter(_EchoAdapter):
    def parse_response(self, stdout):
        raise ValueError("unexpected output shape")


async def test_parse_failure_surfaces_as_cli_handler_error(monkeypatch):
    _install_settings(monkeypatch)

    with pytest.raises(CliHandlerError, match="_BrokenParserAdapter") as exc_info:
        await _BrokenParserAdapter().chat_completion(model="m", system="s", user="u")
    assert isinstance(exc_info.value.__cause__, ValueError)


class _NonTextParserAdapter(_EchoAdapter):
    def parse_response(self, stdout):
        return CliResponse(text={"summary": "looks good"})


async def test_non_string_text_from_parse_response_surfaces_as_cli_handler_error(monkeypatch):
    _install_settings(monkeypatch)

    with pytest.raises(CliHandlerError, match="_NonTextParserAdapter.*not str"):
        await _NonTextParserAdapter().chat_completion(model="m", system="s", user="u")


async def test_cli_handler_error_from_parse_response_propagates_unwrapped(monkeypatch):
    _install_settings(monkeypatch)
    reported = CliHandlerError("reported failure")

    class _ReportingAdapter(_EchoAdapter):
        def parse_response(self, stdout):
            raise reported

    with pytest.raises(CliHandlerError) as exc_info:
        await _ReportingAdapter().chat_completion(model="m", system="s", user="u")
    assert exc_info.value is reported


class _RealProcessAdapter(_EchoAdapter):
    async def _run(self, command):
        return await CliAIHandler._run(self, command)


async def test_run_returns_stdout_of_a_successful_process(monkeypatch):
    _install_settings(monkeypatch)
    handler = _RealProcessAdapter()
    command = CliCommand(argv=[sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"], stdin="hi")

    assert (await handler._run(command)).strip() == "HI"


async def test_run_raises_on_non_zero_exit_with_stderr_tail(monkeypatch):
    _install_settings(monkeypatch)
    handler = _RealProcessAdapter()
    command = CliCommand(argv=[sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"])

    with pytest.raises(CliHandlerError, match="exited with 3: stderr: boom"):
        await handler._run(command)


async def test_run_raises_with_stdout_detail_on_non_zero_exit_when_stderr_is_empty(monkeypatch):
    # Carry the stdout detail in the raised message: Claude Code reports most failures (not logged
    # in, model not found, rate limit) as an `is_error` JSON result on stdout while exiting 1 and
    # writing nothing to stderr, so the stderr tail alone would come up empty.
    _install_settings(monkeypatch)
    handler = _RealProcessAdapter()
    script = (
        "import sys; "
        "sys.stdout.write('{\"type\": \"result\", \"is_error\": true, \"result\": \"boom\"}'); "
        "sys.exit(1)"
    )
    command = CliCommand(argv=[sys.executable, "-c", script])

    with pytest.raises(CliHandlerError) as exc_info:
        await handler._run(command)
    message = str(exc_info.value)
    assert "exited with 1" in message
    assert '"is_error": true' in message
    assert '"boom"' in message
    assert "stdout:" in message
    assert "stderr:" not in message


async def test_run_raises_on_timeout(monkeypatch):
    _install_settings(monkeypatch)
    monkeypatch.setenv("PR_AGENT_CLI_TIMEOUT", "0.2")
    handler = _RealProcessAdapter()
    command = CliCommand(argv=[sys.executable, "-c", "import time; time.sleep(5)"])

    with pytest.raises(CliHandlerError, match="timed out"):
        await handler._run(command)


async def test_run_raises_when_binary_is_missing(monkeypatch):
    _install_settings(monkeypatch)
    handler = _RealProcessAdapter()

    with pytest.raises(CliHandlerError, match="command not found"):
        await handler._run(CliCommand(argv=["/nonexistent/pr-agent-cli-binary"]))


async def test_run_raises_when_binary_is_not_executable(monkeypatch, tmp_path):
    _install_settings(monkeypatch)
    handler = _RealProcessAdapter()
    binary = tmp_path / "not-executable"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o644)

    with pytest.raises(CliHandlerError, match="_RealProcessAdapter") as exc_info:
        await handler._run(CliCommand(argv=[str(binary)]))
    assert str(binary) in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, PermissionError)
    assert exc_info.value.__cause__.errno == errno.EACCES


async def test_run_raises_when_an_argument_contains_a_nul_byte(monkeypatch):
    _install_settings(monkeypatch)
    handler = _RealProcessAdapter()

    with pytest.raises(CliHandlerError, match="_RealProcessAdapter") as exc_info:
        await handler._run(CliCommand(argv=[sys.executable, "-c", "pass", "a\x00b"]))
    assert "embedded null byte" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, ValueError)


async def test_run_kills_process_tree_on_timeout(monkeypatch):
    # Spawn a grandchild from the direct child that inherits stdout/stderr and outlives it: a plain
    # process.kill() on the direct child would leave the grandchild holding the pipes open, so
    # communicate() would not see EOF until the grandchild's multi-second sleep ends.
    _install_settings(monkeypatch)
    monkeypatch.setenv("PR_AGENT_CLI_TIMEOUT", "0.3")
    handler = _RealProcessAdapter()
    script = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)']); "
        "time.sleep(5)"
    )
    command = CliCommand(argv=[sys.executable, "-c", script])

    start = time.monotonic()
    with pytest.raises(CliHandlerError, match="timed out"):
        await handler._run(command)
    elapsed = time.monotonic() - start

    assert elapsed < 2


async def test_run_kills_process_group_on_cancellation(monkeypatch, tmp_path):
    _install_settings(monkeypatch)
    handler = _RealProcessAdapter()
    pid_file = tmp_path / "pid"
    partial_file = tmp_path / "pid.partial"
    # Write the pid aside and rename it into place, so the test never reads a created but still empty file.
    script = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(partial_file)!r}).write_text(str(os.getpid())); "
        f"os.replace({str(partial_file)!r}, {str(pid_file)!r}); "
        "time.sleep(5)"
    )
    command = CliCommand(argv=[sys.executable, "-c", script])

    task = asyncio.ensure_future(handler._run(command))
    while not pid_file.exists():
        await asyncio.sleep(0.01)
    pid = int(pid_file.read_text())

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


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


@pytest.mark.parametrize("model", ["anthropic/-rf", "openrouter/--claude", "x/.hidden"])
def test_map_model_rejects_a_last_segment_outside_the_model_pattern(monkeypatch, model):
    _install_settings(monkeypatch)
    with pytest.raises(CliHandlerError, match="invalid model name"):
        _EchoAdapter().map_model(model)


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


async def test_run_redacts_a_credential_that_straddles_the_start_of_the_error_tail(monkeypatch):
    _install_settings(monkeypatch)
    monkeypatch.setenv("ECHO_API_KEY", "echo-api-key-value")
    handler = _RealProcessAdapter()
    # Write 2008 characters, so the 2000-character tail the error keeps starts inside the credential.
    failing = "import sys; sys.stderr.write('echo-api-key-value' + 'x' * 1990); sys.exit(1)"

    with pytest.raises(CliHandlerError) as exc_info:
        await handler._run(CliCommand(argv=[sys.executable, "-c", failing]))
    assert "key-value" not in str(exc_info.value)


_PRINT_KEY_AS_JSON = (
    "import json, os, sys; "
    "print(json.dumps({'is_error': sys.argv[1] == 'error', 'result': 'key: ' + os.environ['ECHO_API_KEY']}))"
)
# JSON escapes a quote or a backslash, so the raw-stdout redaction in _run cannot match these credentials.
_ESCAPED_SECRETS = pytest.mark.parametrize("secret", ['pa"ssword-value', "pa\\ssword-value"],
                                           ids=["quote", "backslash"])


class _JsonProcessAdapter(_RealProcessAdapter):
    """Decode a real child's JSON output, as the adapters decode their CLI's output."""
    outcome = "ok"
    raised = None

    def build_command(self, model, system, user):
        return CliCommand(argv=[sys.executable, "-c", _PRINT_KEY_AS_JSON, self.outcome])

    def parse_response(self, stdout):
        data = json.loads(stdout)
        if data["is_error"]:
            self.raised = CliHandlerError(f"echo reported an error: {data['result']}")
            raise self.raised
        return CliResponse(text=data["result"])


class _JsonFieldParserAdapter(_JsonProcessAdapter):
    def parse_response(self, stdout):
        raise ValueError(f"unexpected result {json.loads(stdout)['result']}")


@_ESCAPED_SECRETS
async def test_chat_completion_redacts_a_json_escaped_credential_from_the_text_and_the_log(monkeypatch, secret):
    _install_settings(monkeypatch)
    monkeypatch.setenv("ECHO_API_KEY", secret)
    logged = []
    monkeypatch.setattr(cli_module, "get_logger", lambda: SimpleNamespace(
        debug=lambda *a, **kw: None, info=lambda msg, **kw: logged.append(kw)))
    assert secret not in json.dumps(secret)

    text, _ = await _JsonProcessAdapter().chat_completion(model="m", system="s", user="u")

    assert text == "key: [REDACTED]"
    assert [entry["response"] for entry in logged] == ["key: [REDACTED]"]


@_ESCAPED_SECRETS
async def test_chat_completion_redacts_a_json_escaped_credential_from_a_reported_error(monkeypatch, secret):
    _install_settings(monkeypatch)
    monkeypatch.setenv("ECHO_API_KEY", secret)
    handler = _JsonProcessAdapter()
    handler.outcome = "error"

    with pytest.raises(CliHandlerError) as exc_info:
        await handler.chat_completion(model="m", system="s", user="u")

    assert exc_info.value is handler.raised
    assert str(exc_info.value) == "echo reported an error: key: [REDACTED]"


@_ESCAPED_SECRETS
async def test_chat_completion_redacts_a_json_escaped_credential_from_a_parse_failure(monkeypatch, secret):
    _install_settings(monkeypatch)
    monkeypatch.setenv("ECHO_API_KEY", secret)

    with pytest.raises(CliHandlerError) as exc_info:
        await _JsonFieldParserAdapter().chat_completion(model="m", system="s", user="u")

    assert secret not in str(exc_info.value)
    assert "unexpected result key: [REDACTED]" in str(exc_info.value)


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
