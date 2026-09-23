# Changelog

## 0.1.0 (unreleased)

- Run PR-Agent through the Claude Code CLI and the Codex CLI.
- Read handler settings from `PR_AGENT_CLI_*` environment variables only.
- Pass each CLI an allowlisted environment and redact credential values from its output.
- Add the `pr-agent-cli-handlers` command, a composite GitHub Action and a GitLab pipeline template.
