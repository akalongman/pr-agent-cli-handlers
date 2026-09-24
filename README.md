# pr-agent-cli-handlers

Run [PR-Agent](https://github.com/The-PR-Agent/pr-agent) through a local agent CLI (the Claude Code CLI or the
OpenAI Codex CLI) instead of LiteLLM API calls. Review pull requests and merge requests with a subscription you
already have, or with an API key, locally or in your own CI, with no server and no fork of PR-Agent.

This project is not affiliated with Anthropic, OpenAI, Google or the PR-Agent maintainers. It runs each
vendor's published CLI unmodified. It never reads or stores a credential and only passes allowlisted variables
through to the CLI.

## How it works

`pr-agent-cli-handlers` installs PR-Agent as a dependency and replaces the default AI handler of PR-Agent's
commands with a handler that runs the selected CLI once per model call, so `describe`, `review`, `improve`,
`ask` and the other commands send their model calls through that CLI. Code paths that call LiteLLM directly,
such as MOSAICO, are not covered. The command stops with exit status 2 if the installed PR-Agent no longer
has the constructors it relies on.

## Install

The CLI you choose must be installed and logged in on the same machine.

| Platform | Install this package | Claude Code CLI | Codex CLI |
|---|---|---|---|
| macOS | `brew install uv && uv tool install pr-agent-cli-handlers` | `npm install -g @anthropic-ai/claude-code` | `npm install -g @openai/codex` |
| Linux (Debian, Ubuntu) | `curl -LsSf https://astral.sh/uv/install.sh \| sh && uv tool install pr-agent-cli-handlers` | `npm install -g @anthropic-ai/claude-code` | `npm install -g @openai/codex` |
| Linux (other) | `pipx install pr-agent-cli-handlers` (Python 3.12 or later) | as above | as above |
| Windows (PowerShell) | native Windows is untested and not supported in 0.1.0: run `wsl --install`, then follow the WSL row | use WSL | use WSL |
| WSL | follow the Linux rows inside your WSL distribution | as Linux | as Linux |

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
| `PR_AGENT_CLI_HANDLER` | `claude_code` or `codex` | required |
| `PR_AGENT_CLI_BINARY` | CLI executable name or path | `claude` or `codex` |
| `PR_AGENT_CLI_EXTRA_ARGS` | extra CLI arguments, split like shell words | empty |
| `PR_AGENT_CLI_TIMEOUT` | seconds per call, a positive number | PR-Agent's `config.ai_timeout` |
| `PR_AGENT_CLI_PASS_ENV` | comma-separated names of extra environment variables to pass to the CLI | empty |

The model, fallback models and reasoning effort come from PR-Agent's own settings (`CONFIG__MODEL`,
`CONFIG__FALLBACK_MODELS`, `CONFIG__REASONING_EFFORT`).

The command keeps PR-Agent's exit semantics: a failed `review`, `describe` or `improve` still exits with
status 0. A CI job that must fail when a review fails sets `CONFIG__PROPAGATE_TOOL_ERRORS=true`, in the action
step's `env` or the GitLab job's `variables`.

## Credentials

| CLI | Subscription | API key |
|---|---|---|
| Claude Code | `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` (Pro, Max, Team, Enterprise); tied to the person who created it | `ANTHROPIC_API_KEY`, or Bedrock and Vertex through their own variables |
| Codex | ChatGPT login saved by `codex login`; in CI this is experimental | `OPENAI_API_KEY` or `CODEX_API_KEY` |

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
    if: ${{ github.event.sender.type != 'Bot' && (github.event_name != 'issue_comment' || (github.event.issue.pull_request && startsWith(github.event.comment.body, '/'))) }}
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

The condition starts a run for a comment only on a pull request and only when the comment starts with `/`; an
unknown slash command (a typo such as `/reviwe`) fails the run, unlike a failed review.

`pull_request` gives fork pull requests no secrets, so they are skipped. `pull_request_target` would review
them with secrets present; the action never checks out pull request code, but a fork's diff can still carry
instructions aimed at the reviewer.

## GitLab

Include `templates/gitlab-ci.yml` from a release tag, or copy its job, and set these masked CI/CD variables (and
hidden, where GitLab offers it): `GITLAB_PERSONAL_ACCESS_TOKEN` and the CLI credential (for example
`CLAUDE_CODE_OAUTH_TOKEN`). Protecting them is a trade-off: a merge request pipeline receives protected variables
only when the project allows merge request pipelines to access them and both source and target branches are
protected, while an unprotected variable can be read by anyone who can push a branch, through a modified pipeline.
Do not run parent-project pipelines for merge requests from forks while these variables are present.

## Security

- Each CLI receives only an allowlisted environment: process basics, locale, proxies and CA bundles, its own
  credential and configuration variables, and the names in `PR_AGENT_CLI_PASS_ENV`. Git provider tokens such
  as `GITHUB_TOKEN`, `GITLAB__PERSONAL_ACCESS_TOKEN` and `CI_JOB_TOKEN` never reach it unless you list them in
  `PR_AGENT_CLI_PASS_ENV`.
- Anything a CLI prints is checked for credential values and redacted before PR-Agent sees it. This catches
  exact values only.
- Claude Code runs with its tools switched off, and Codex with its tool features switched off. Claude Code also
  runs with `DISABLE_AUTOUPDATER=1`, so the installed (pinned) version serves every call of a job.
- Model names must be plain identifiers, because a repository can set `config.model`.

## Limitations

- Webhook servers (GitHub App, GitLab webhook and the others) may work but are not tested yet.
- MOSAICO is not supported: it calls LiteLLM directly.
- The package includes an experimental adapter for the Antigravity CLI (`agy`) that is not selectable, because
  on agy 1.2.9 it failed the live gate (its reviews derail into tool use it cannot switch off).

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
