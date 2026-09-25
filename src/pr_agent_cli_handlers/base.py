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
from dataclasses import dataclass, field
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
        self.timeout = read_timeout(os.environ, get_settings().config.ai_timeout)
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

        Drop every provider prefix, so ``openrouter/anthropic/claude-x`` becomes ``claude-x``. Check the segment
        against the pattern too, so ``anthropic/--claude`` cannot reach the CLI as a flag.
        """
        if isinstance(model, str) and MODEL_NAME.fullmatch(model):
            name = model.rsplit("/", 1)[-1]
            if MODEL_NAME.fullmatch(name):
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

    @staticmethod
    def write_private_file(directory: str, text: str, prefix: str) -> str:
        """Write ``text`` to a new file in ``directory`` that only this user can read, and return its path.

        Use a new name per call: parallel calls on one handler share its directories.
        """
        try:
            fd, path = tempfile.mkstemp(prefix=prefix, suffix=".txt", dir=directory)
        except OSError as e:
            raise CliHandlerError(f"cannot create a private file in {directory}: {e}") from e
        try:
            # Write line endings as given; text mode would turn "\n" into "\r\n" on Windows.
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except UnicodeEncodeError as e:
            with suppress(FileNotFoundError):
                os.remove(path)
            raise CliHandlerError(f"cannot write the prompt as UTF-8: {e.reason}") from e
        except OSError as e:
            with suppress(FileNotFoundError):
                os.remove(path)
            raise CliHandlerError(f"cannot write the private file {path}: {e}") from e
        except BaseException:
            with suppress(FileNotFoundError):
                os.remove(path)
            raise
        return path

    @staticmethod
    def _remove_temp_files(command: CliCommand) -> None:
        """Remove the command's temporary files; log a failure instead of raising it, since this runs in finally."""
        for path in command.temp_files:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError as e:
                get_logger().warning(f"Cannot remove the temporary file {path}: {e}")

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
        # Redact again after parsing: JSON escaping (a quote, a backslash) hides a credential from the redaction
        # _run applies to the raw stdout, and decoding restores the plain value.
        secrets = self.credential_values()
        try:
            response = self.parse_response(stdout)
            # Refuse non-text here, inside the guard: redaction needs a str, and callers expect text back.
            if not isinstance(response.text, str):
                raise TypeError(f"parse_response returned {type(response.text).__name__} text, not str")
        except CliHandlerError as e:
            # Redact the message in place and re-raise the same object the adapter raised.
            e.args = tuple(redact(arg, secrets) if isinstance(arg, str) else arg for arg in e.args)
            raise
        except Exception as e:
            raise CliHandlerError(redact(
                f"{type(self).__name__}: cannot parse the output of {command.argv[0]}: {type(e).__name__}: {e}",
                secrets)) from e
        response.text = redact(response.text, secrets)
        # Prefer the model the CLI reports: an alias such as ``opus`` resolves to a concrete model there.
        reported_model = response.models[0] if len(response.models) == 1 else mapped_model
        get_logger().info(
            f"AI response from {reported_model} (effort {command.effort or 'default'}): "
            f"{response.prompt_tokens} prompt tokens, {response.completion_tokens} completion tokens",
            response=response.text, finish_reason=response.finish_reason, model=mapped_model,
            models_used=list(response.models), effort=command.effort,
            prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens)
        usage = {
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.prompt_tokens + response.completion_tokens,
        }
        record_ai_call(usage, model=reported_model, cost_usd=response.cost_usd)
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
                # Redact before cutting the tail, so the cut cannot leave part of a credential unmatched.
                stream_tail = redact(stream.decode("utf-8", errors="replace"), secrets)[-2000:]
                if stream_tail:
                    detail_parts.append(f"{label}: {stream_tail}")
            detail = "; ".join(detail_parts)
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
