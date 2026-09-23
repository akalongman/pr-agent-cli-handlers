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
        text = last_error = None
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
                detail = str(event.get("message") or event.get("error") or event)[:500]
                if kind == "turn.failed":
                    raise CliHandlerError(f"Codex reported a failure: {detail}")
                # Keep the message only: Codex prints an error event for each transient stream retry and goes on.
                last_error = detail
                continue
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
            message = "Codex produced no agent message"
            if last_error:
                message += f" (last error: {last_error})"
            raise CliHandlerError(message)
        return CliResponse(text=text, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
