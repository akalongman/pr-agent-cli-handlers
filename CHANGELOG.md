# Changelog

## 0.1.0 (unreleased)

- Run PR-Agent through the Claude Code CLI and the Codex CLI.
- Require PR-Agent 0.48 or later with its `github` and `gitlab` extras, which 0.48 split out of the core install.
- Read handler settings from `PR_AGENT_CLI_*` environment variables only.
- Pass each CLI an allowlisted environment and redact credential values from its output.
- Add the `pr-agent-cli-handlers` command, a composite GitHub Action and a GitLab pipeline template.
- Pass Claude Code's system prompt through a private file, so long instructions fit and stay out of the process list.
- Log the model and reasoning effort of each CLI call, and file its cost under the model the CLI reports.
