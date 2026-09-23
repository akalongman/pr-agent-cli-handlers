"""Run Claude Code headless (``claude -p``) once per call.

The flag set turns the harness into a plain completion: its own system prompt is replaced,
tools, settings files and MCP servers are off, and nothing is persisted. Authentication is
the harness's own login; this adapter reads no credentials.
"""
import json

from pr_agent_cli_handlers.base import MODEL_NAME, CliAIHandler, CliCommand, CliResponse
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
            # Check the stripped name again, so ``anthropic.--claude`` cannot reach the CLI as a flag.
            if not MODEL_NAME.fullmatch(name):
                raise CliHandlerError(f"{type(self).__name__}: invalid model name {model!r}")
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
