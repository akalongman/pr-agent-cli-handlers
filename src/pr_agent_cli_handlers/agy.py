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
