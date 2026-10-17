# pr-agent-cli-handlers

Run [PR-Agent](https://github.com/The-PR-Agent/pr-agent) through a local agent CLI (the Claude Code CLI or the
OpenAI Codex CLI) instead of LiteLLM API calls. Review pull requests and merge requests with an API key, or, for
your own runs, with the Claude Code or Codex subscription you already have, locally or in your own CI, with no
server and no fork of PR-Agent.

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

The CLI you choose must be installed and logged in on the same machine. The package requires PR-Agent 0.48 or
later and installs it with the `github` and `gitlab` extras, which 0.48 split out of the core install. For another
git provider, add its extra when you install: `uv tool install pr-agent-cli-handlers --with 'pr-agent[bitbucket]'`
or `pipx inject pr-agent-cli-handlers 'pr-agent[bitbucket]'`.

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
| `PR_AGENT_CLI_PASS_ENV` | comma-separated names of extra environment variables to pass to the CLI, including the CLI's own switches | empty |

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

The command keeps PR-Agent's exit semantics: a failed `review`, `describe` or `improve` still exits with
status 0. A CI job that must fail when a review fails sets `CONFIG__PROPAGATE_TOOL_ERRORS=true`, in the action
step's `env` or the GitLab job's `variables`.

## Credentials

API keys are the default. A subscription login is for runs made by the person who owns it, for example reviewing
your own branch before you open the pull request. A subscription token cannot be scoped or capped the way an API
key with a spending limit can, and both vendors say where they expect each kind of credential.

| CLI | API key (default) | Subscription |
|---|---|---|
| Claude Code | `ANTHROPIC_API_KEY`, or Bedrock and Vertex through their own variables | `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` (Pro, Max, Team, Enterprise). Anthropic documents it for CI pipelines and scripts; it is tied to the subscription of the person who ran the command |
| Codex | `OPENAI_API_KEY` or `CODEX_API_KEY` | `codex login` with a ChatGPT account. OpenAI documents it for automation only through Enterprise access tokens on trusted, private runners, or a copied `~/.codex/auth.json`, which "contains access tokens" and is to be treated like a password |

**Anthropic.** The [Claude Code legal and compliance page](https://code.claude.com/docs/en/legal-and-compliance)
(read 2026-10-17) says OAuth login "is designed to support ordinary use of Claude Code and other native Anthropic
applications", that "advertised usage limits for Pro and Max plans assume ordinary, individual usage", and that
developers "building products or services that interact with Claude's capabilities" should use API key
authentication and may not "route requests through Free, Pro, or Max plan credentials on behalf of their users".
The same page does not prevent "an end user from signing in to the unmodified Claude Code binary with their own
Claude subscription", and Anthropic's [GitHub Actions page](https://code.claude.com/docs/en/github-actions)
accepts `CLAUDE_CODE_OAUTH_TOKEN` while advising an API key for a secret shared across repositories, "since an
OAuth token is tied to the subscription of the person who ran `claude setup-token`". This package runs the
unmodified binary, never reads the token, and does not pay for or resell anyone's usage. Whether a given run is
ordinary, individual usage of your own subscription is your judgment to make against those terms; Anthropic
"reserves the right to take measures to enforce these restrictions and may do so without prior notice".

**OpenAI.** The [Codex authentication page](https://developers.openai.com/codex/auth) (read 2026-10-17) says:
"Use API key authentication for programmatic Codex CLI workflows, such as CI/CD jobs. Don't expose Codex execution
in untrusted or public environments."

## GitHub Actions

```yaml
on:
  pull_request:
    types: [opened, reopened, ready_for_review, synchronize]
  issue_comment:
    types: [created]
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
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          CONFIG__FALLBACK_MODELS: '["claude-opus-5"]'
```

For a repository where every run is your own, `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` can replace
`ANTHROPIC_API_KEY`; see [Credentials](#credentials) before you do.

The condition starts a run for a comment only on a pull request and only when the comment starts with `/`; an
unknown slash command (a typo such as `/reviwe`) fails the run, unlike a failed review.

`pull_request` gives fork pull requests no secrets, so they are skipped. `pull_request_target` would review
them with secrets present; the action never checks out pull request code, but a fork's diff can still carry
instructions aimed at the reviewer.

The action's own steps run on Node 24, so a self-hosted runner needs Actions Runner 2.327.1 or later.

## GitLab

Include `templates/gitlab-ci.yml` from a release tag, or copy its job, and set these masked CI/CD variables (and
hidden, where GitLab offers it): `GITLAB_PERSONAL_ACCESS_TOKEN` and the CLI credential (for example
`ANTHROPIC_API_KEY`). Protecting them is a trade-off: a merge request pipeline receives protected variables
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
- Claude Code reads PR-Agent's system prompt from a file only you can read, removed after each call, so it does not
  appear in the process list. Codex still receives it as a command-line argument.
- Model names must be plain identifiers, because a repository can set `config.model`.

## Limitations

- Webhook servers (GitHub App, GitLab webhook and the others) may work but are not tested yet.
- MOSAICO is not supported: it calls LiteLLM directly.
- The package includes an experimental adapter for the Antigravity CLI (`agy`) that is not selectable, because
  on agy 1.2.9 it failed the live gate (its reviews derail into tool use it cannot switch off).
- With the Codex handler, PR-Agent's system prompt (including `extra_instructions`) must stay under about
  120,000 bytes, because it travels as one command-line argument.

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
