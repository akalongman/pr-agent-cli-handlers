# pr-agent-cli-handlers: design

Status: draft for review. Date: 2026-09-23. Credentials and compliance revised 2026-10-17.

## Summary

`pr-agent-cli-handlers` is an add-on package for [PR-Agent](https://github.com/The-PR-Agent/pr-agent). It runs PR-Agent's tools through a local agent command-line tool (the Claude Code CLI or the OpenAI Codex CLI; an experimental adapter for the Antigravity CLI `agy` is included but not selectable) instead of LiteLLM API calls. A user can review pull requests and merge requests with an API key, or, for their own runs, with a subscription they already pay for, locally or in their own CI, with no server and no fork of PR-Agent.

## Background

### Upstream position

Feature request [The-PR-Agent/pr-agent#3640](https://github.com/The-PR-Agent/pr-agent/issues/3640) proposed two parts: selecting the AI handler through configuration, and handlers backed by the Claude Code and Codex CLIs. A collaborator answered on 2026-09-23:

- Part 2 stays declined, following the maintainer's earlier decisions in #2193 and #2353.
- Part 1 is on hold. Before v1 the project takes bug fixes and work aligned with what exists, and the agent-runtime RFC ([Discussion #3147](https://github.com/The-PR-Agent/pr-agent/discussions/3147)) may change how handlers are chosen.

A follow-up comment argued for part 1 together with a `register_ai_handler` hook mirroring `register_git_provider`. On 2026-10-16 the maintainer closed the issue as not planned, calling the subscription handlers "tricky legally" and declining them in the core code. Both parts now live only in this package.

### Landscape, checked 2026-09-23

- [alibaba/open-code-review](https://github.com/alibaba/open-code-review) (Apache-2.0, about 40,000 stars since May 2026) already offers agentic, precision-focused review with GitHub Actions and GitLab CI recipes. Its CI path requires an API endpoint and token (`OCR_LLM_URL`, `OCR_LLM_AUTH_TOKEN`). Its maintainers closed a Codex and Claude CLI provider in favor of an interactive "delegation mode" ([PR #180](https://github.com/alibaba/open-code-review/pull/180)) and declined reusing a Claude subscription login ([#331](https://github.com/alibaba/open-code-review/issues/331)). A ChatGPT-subscription pull request ([#1106](https://github.com/alibaba/open-code-review/pull/1106)) has been open since 2026-08-28.
- [Nikita-Filonov/ai-review](https://github.com/Nikita-Filonov/ai-review) (Apache-2.0) runs a repository-exploring agent loop across GitHub, GitLab, Bitbucket, Azure DevOps and Gitea, with API keys.
- Demand for subscription-backed review is visible on both large trackers: PR-Agent #2193, #2353 and #3640; Open Code Review #331, #1105 and #1106.

### Why an add-on

- A new general-purpose reviewer would compete with Open Code Review on the features it already leads on.
- A fork would absorb upstream churn: 488 commits in the 30 days to 2026-09-23. The existing files the CLI-handler branch modifies took up to 62 commits in that period (`pr_agent/settings/configuration.toml`), including security-sensitive ones (`pr_agent/config_security.py`, 7 commits).
- An add-on changes no upstream file. It relies on a pattern PR-Agent uses consistently: constructors that take an `ai_handler` factory whose default is `LiteLLMAIHandler`.

## Goals

1. Run PR-Agent's commands through an agent CLI: `describe`, `review` and `improve`, and every other command whose constructor takes the `ai_handler` default.
2. Support the Claude Code CLI and the Codex CLI. Support `agy` if its probes pass.
3. Work locally, in GitHub Actions and in GitLab merge request pipelines, with no server.
4. Never read, store, log or forward a credential beyond the environment the CLI itself needs.
5. Stay current with upstream through the dependency version, never through merges.

## Non-goals

- Webhook servers (GitHub App, GitLab webhook, Bitbucket, Azure DevOps, Gitea). They may work through the same activation, but the first release neither tests nor documents them.
- MOSAICO. It calls LiteLLM directly (`pr_agent/mosaico/executor.py`).
- Agentic review. PR-Agent's prompts expect a plain completion, and the adapters keep tools off where the CLI allows it.
- Hosted or multi-tenant operation.
- Docker images. The package is installed at job start.

## Requirements

- **R1.** The package is `pr-agent-cli-handlers`, MIT-licensed, for Python 3.12 and later. Its only runtime dependency is `pr-agent[github,gitlab]>=0.48,<1`: 0.48.0 moved the git provider SDKs into extras, and v1 is expected to change how AI handlers are chosen (revised 2026-10-17 from `pr-agent>=0.46` with no upper bound).
- **R2.** `pr-agent-cli-handlers [arguments]` behaves like `pr-agent [arguments]` with the selected CLI handler. `pr-agent-cli-handlers action` runs PR-Agent's GitHub Action runner with it.
- **R3.** Activation replaces the `ai_handler` default of every constructor listed under [Activation](#activation), only inside the process the command starts.
- **R4.** Before activation, a seam check exits with status 2 if `PRAgent`, `PRReviewer`, `PRDescription` or `PRCodeSuggestions` lacks an `ai_handler` parameter whose default is `LiteLLMAIHandler`. The message names the constructor and the installed PR-Agent version. The same condition on any other listed constructor logs a warning.
- **R5.** `PR_AGENT_CLI_HANDLER` selects the adapter: `claude_code` or `codex`, and `agy` once P3 passes. Any other value, or none, exits with status 2 before PR-Agent starts, listing the valid values.
- **R6.** Handler settings come from the process environment only, never from PR-Agent's settings object, so a repository's `.pr_agent.toml` cannot reach them. See [Configuration](#configuration).
- **R7.** A model name must match `^[A-Za-z0-9][A-Za-z0-9._:/@-]*$` before any adapter-specific check. PR-Agent lets a repository set `config.model`, including per directory.
- **R8.** Every failure raises `CliHandlerError`: invalid configuration, launch (missing binary, permission, argument too long, NUL byte in an argument), timeout, non-zero exit, unparseable output and an empty answer (a successful run whose text is empty or only whitespace). `CliHandlerError` subclasses PR-Agent's `FallbackEligibleError`, so PR-Agent's fallback loop then moves to the next model.
- **R9.** The CLI process receives only an allowlisted environment. See [Child environment](#child-environment).
- **R10.** Before returning a response, the handler replaces every occurrence of a credential value with `[REDACTED]`. Credential values are the values of the adapter's allowlisted credential variables, plus any variable in the parent environment whose name contains `TOKEN`, `KEY`, `SECRET` or `PASSWORD` (compared case-insensitively) and whose value is at least 8 characters long. This is defense in depth for adapters that keep tool access; it does not catch encoded or transformed secrets.
- **R11.** No command-line argument exceeds 120,000 bytes. Adapters pass the user prompt on standard input, and the Claude Code adapter passes the system prompt through a file. The Codex adapter's system prompt still travels in argv as `developer_instructions` and is bounded by this limit.
- **R12.** A timeout kills the CLI's whole process group.
- **R13.** Prompts are logged at debug level (`get_logger().debug("Prompts", artifact={...})`, PR-Agent's own idiom), and the response at info level with a message naming the model the CLI reports (or the requested one) and the effort the adapter passed. No credential is ever logged.
- **R14.** Each successful call is recorded with PR-Agent's `record_ai_call`, with token counts and cost when the CLI reports them, under the model the CLI reports when it reports exactly one, else the requested model.
- **R15.** No automated test runs a real agent CLI.

## Design

### Package layout

The handler code comes from the fork branch [`akalongman/pr-agent` `feature/cli-ai-handlers`](https://github.com/akalongman/pr-agent/tree/feature/cli-ai-handlers) at `6c707fe6`, where it went through task and final reviews:

- `pr_agent/algo/ai_handlers/cli_ai_handler.py` becomes the shared base.
- `pr_agent/algo/ai_handlers/claude_code_ai_handler.py` and `codex_ai_handler.py` become the first two adapters.
- `tests/unittest/test_cli_ai_handler.py`, `test_claude_code_ai_handler.py` and `test_codex_ai_handler.py` become the starting test suite.

The branch's registry (`registry.py`) and its `config_security.py` changes are not carried over. New modules are the activation code, the `agy` adapter, the environment allowlist and the redaction step. The package lives under `src/pr_agent_cli_handlers/`.

### Activation

The command runs these steps in order:

1. Read and validate `PR_AGENT_CLI_HANDLER` (R5) and the other handler variables (R6).
2. Run the seam check (R4) over the constructors below. For each one, `inspect.signature` must show an `ai_handler` parameter whose default is `LiteLLMAIHandler`.
3. Replace that default in the function's `__defaults__` (or `__kwdefaults__`) with the selected adapter class.
4. Call `pr_agent.cli.run()` for the CLI form, or `pr_agent.servers.github_action_runner.main()` for `action`.

Constructors with an `ai_handler` default of `LiteLLMAIHandler` in PR-Agent 0.46.0, found by a syntax-tree scan (unchanged in 0.48.0, re-scanned 2026-10-17):

| Module | Constructor | Seam check |
|---|---|---|
| `pr_agent/agent/pr_agent.py` | `PRAgent.__init__` | required |
| `pr_agent/tools/pr_reviewer.py` | `PRReviewer.__init__` | required |
| `pr_agent/tools/pr_description.py` | `PRDescription.__init__` | required |
| `pr_agent/tools/pr_code_suggestions.py` | `PRCodeSuggestions.__init__` | required |
| `pr_agent/tools/pr_questions.py` | `PRQuestions.__init__` | warning |
| `pr_agent/tools/pr_line_questions.py` | `PR_LineQuestions.__init__` | warning |
| `pr_agent/tools/pr_update_changelog.py` | `PRUpdateChangelog.__init__` | warning |
| `pr_agent/tools/pr_add_docs.py` | `PRAddDocs.__init__` | warning |
| `pr_agent/tools/pr_generate_labels.py` | `PRGenerateLabels.__init__` | warning |
| `pr_agent/tools/pr_help_message.py` | `PRHelpMessage.__init__` | warning |
| `pr_agent/tools/pr_help_docs.py` | `PRHelpDocs.__init__` | warning |

Patching `PRAgent` alone is not enough. The GitHub Action runner's automatic runs construct `PRDescription(pr_url)`, `PRReviewer(pr_url)` and `PRCodeSuggestions(pr_url)` directly (`_run_auto_tool` in `pr_agent/servers/github_action_runner.py`), so those constructors' own defaults apply. The one direct construction, `LiteLLMAIHandler()` in `pr_agent/mosaico/executor.py`, is outside the supported surface.

An explicit command was chosen over a `.pth` start-up hook. The hook would activate in every Python process of the environment and be invisible when debugging.

### Configuration

| Variable | Meaning | Default |
|---|---|---|
| `PR_AGENT_CLI_HANDLER` | `claude_code` or `codex`; `agy` once P3 passes | required |
| `PR_AGENT_CLI_BINARY` | CLI executable name or path | `claude`, `codex` or `agy` |
| `PR_AGENT_CLI_EXTRA_ARGS` | extra CLI arguments, split with `shlex.split`; an unparseable value raises `CliHandlerError` naming the variable | empty |
| `PR_AGENT_CLI_TIMEOUT` | seconds per call, a positive number; any other non-empty value raises `CliHandlerError` naming the variable | `config.ai_timeout` |
| `PR_AGENT_CLI_PASS_ENV` | comma-separated names of extra variables to pass to the CLI; names are trimmed, empty entries ignored, and a name with characters outside `[A-Za-z0-9_]` raises `CliHandlerError` | empty |

The names use single underscores. PR-Agent's settings loader is created with `envvar_prefix=False`, so any `SECTION__KEY` variable becomes a setting.

The model, fallback models and reasoning effort still come from PR-Agent's settings (`CONFIG__MODEL`, `CONFIG__FALLBACK_MODELS`, `CONFIG__REASONING_EFFORT`), subject to R7. The documentation states that fallback models must be models the selected CLI accepts (PR-Agent's default fallback is an OpenAI model, which the Claude Code adapter rejects), and that models PR-Agent does not know need `config.custom_model_max_tokens`.

### Handlers

**Carried over unchanged in behavior:**

- **Failure contract:** R8, including the NUL-byte and non-list cases fixed on the branch. With environment variables, `extra_args` is always a string, so only the unparseable case remains.
- **Size and process control:** the 120,000-byte argument guard (R11) and process-group kill (R12). The CLI starts in its own session (`start_new_session=True` on POSIX).
- **Logging and accounting:** R13 and R14, which now also name the model and effort of each call.
- **Images:** `supports_images = False`; an image path is logged as ignored.

**Claude Code adapter** (argument list as at `6c707fe6`, with the system prompt read from a file):

```
claude -p --restricted --safe-mode --strict-mcp-config --tools "" --no-session-persistence
       --output-format json --system-prompt-file <file> --model <model>
       [--effort low|medium|high|xhigh|max] [extra args]
```

- **Input and tools:** the user prompt goes on standard input, and tools are off.
- **Working directory:** an empty temporary directory, as for Codex.
- **System prompt:** written to a new file that only the user can read, in a second private per-handler directory outside the working directory, passed with `--system-prompt-file`, and removed when the call ends. A long prompt is then not bounded by R11 and does not show in the process list. Verified on 2.1.280 with a 158,536-byte prompt whose last line reached the model (2026-09-25).
- **Model names:** Claude names or the aliases `opus`, `sonnet`, `haiku` and `fable`, after stripping a provider prefix and an `anthropic.` prefix.
- **Output:** a result whose `subtype` is not `success` raises with the subtype named.
- **Environment:** the child environment adds `DISABLE_AUTOUPDATER=1`, set after the allowlist so it also wins over a value passed through `PR_AGENT_CLI_PASS_ENV`.

**Codex adapter** (argument list as at `6c707fe6`, plus the feature switches P4 established):

```
codex --ask-for-approval never --sandbox read-only --model <model>
      --config features.shell_tool=false --config features.unified_exec=false
      --config features.browser_use=false --config features.computer_use=false
      --config features.apps=false --config features.plugins=false
      --config features.view_image=false --config features.image_generation=false
      --config features.in_app_browser=false
      --config project_doc_max_bytes=0
      --config developer_instructions=<TOML string>
      [--config model_reasoning_effort="<effort>"]
      exec --json --ephemeral --ignore-user-config --ignore-rules
      --skip-git-repo-check --color never --cd <empty temporary directory> [extra args] -
```

- **Input and working directory:** the user prompt goes on standard input. The empty working directory is created once per handler instance and removed on garbage collection.
- **Effort:** `low` to `max` pass through; `none` and `minimal` become `low`.
- **Output:** the parser raises on a `turn.failed` event or a missing agent message. `error` events are transient stream retries; the parser keeps only the last one's message, for the missing-message error.
- **Tool access:** the read-only sandbox alone blocks writes and network access but not reads. The `features.*=false` switches remove the shell, command execution, browser, computer-use, apps, plugins and image tools; with them the Codex 0.156.1 prompt shrank from 30,660 to 12,656 input tokens (P4).

**`agy` adapter (experimental; not selectable, because it failed P3 on 1.2.9; P4 decides its trust guidance):**

```
agy --disable-slash-commands --sandbox --input-format stream-json --output-format stream-json
    --model <model> [extra args]
```

- **No `-p`:** `-p` takes the prompt as its value, and `--input-format stream-json` refuses a command-line prompt. The stream-json form runs one turn per input line and needs no `-p` (P2).
- **Input:** standard input carries one line, `{"event": "user", "message": {"content": "<system>\n\n<user>"}}`. `agy` has no system-prompt override (feature requests [#50](https://github.com/google-antigravity/antigravity-cli/issues/50) and [#892](https://github.com/google-antigravity/antigravity-cli/issues/892) are open), so PR-Agent's system prompt is prepended to the message.
- **Slash commands:** `--disable-slash-commands`, so text such as `/review` inside a prompt is not expanded.
- **Working directory:** an empty temporary directory, as for Codex.
- **Effort:** never passed. On 1.2.9, `--effort` conflicts with a model name that carries an effort (`gemini-3.8-flash-high`), and the models whose names carry none (`claude-sonnet-4-6`, `claude-opus-4-6-thinking`) reject it as unsupported. The model name selects the effort.
- **Output:** newline-delimited JSON. The line whose `event` is `result` carries `result.status`, `result.response`, `result.error` and `result.usage`. A missing result line, or a `status` other than `SUCCESS`, raises with the status and `error` named. Tokens map as `prompt = usage.input_tokens` and `completion = usage.output_tokens` (`total_tokens` equals their sum; thinking tokens are counted inside output). No cost is reported.
- **Tool access:** `agy` has no switch to disable its tools and keeps its file, shell and web tools. With `--sandbox` and without `--dangerously-skip-permissions`, it read a file outside its working directory in P4. In the P3 runs it called `search_web` with queries built from prompt text and tried to fetch URLs (`read_url_content`) and run commands (`run_command`), so text drawn from a prompt, diff fragments included, can leave the machine. The adapter is therefore documented as for trusted repositories only, and R10 applies.
- **Permissions:** never `--dangerously-skip-permissions`.
- **Overhead:** about 12,600 input tokens of the harness's own prompt per call, measured with a two-word prompt on 1.2.9.
- **Context files:** a sentinel `GEMINI.md` and `AGENTS.md` at the root of a git work tree above the working directory did not reach `agy`'s stored model request (14,324 input tokens against 14,331 without them, 1.2.9). The sentinel run derailed into tool use, so no review output could be checked. A user-level `~/.gemini/GEMINI.md` was not tested.

Before `agy` becomes selectable, all of these must hold on a current release, followed by a passing P3:

- a verified way to stop tool use (untested leads: `--mode plan`, `--json-schema`)
- a check that a user-level `~/.gemini/GEMINI.md` does not load
- a check whether print mode applies the user's `~/.gemini` command allowlist

### Child environment

The CLI process receives only:

- **Base:** `PATH`, `HOME`, `USER`, `LOGNAME`, `LANG`, `LANGUAGE`, `LC_*`, `TZ`, `TMPDIR`, `TEMP`, `TMP`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`, `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `ALL_PROXY` (and their lowercase forms), `SSL_CERT_FILE`, `SSL_CERT_DIR`, `REQUESTS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`.
- **Claude Code:** `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`, `ANTHROPIC_VERTEX_PROJECT_ID`, `CLOUD_ML_REGION`, `GOOGLE_APPLICATION_CREDENTIALS`, `AWS_REGION`, `AWS_PROFILE`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`. The adapter also adds `DISABLE_AUTOUPDATER=1`, a fixed value set after the allowlist and `PR_AGENT_CLI_PASS_ENV` rather than taken from the job.
- **Codex:** `OPENAI_API_KEY`, `CODEX_API_KEY`, `OPENAI_BASE_URL`, `CODEX_HOME`.
- **`agy`:** `GEMINI_API_KEY`. Its cached Google-account login lives under `HOME`; the P3 gate runs `agy` with exactly this allowlisted environment, so a missing variable surfaces there.
- **Extras:** every name listed in `PR_AGENT_CLI_PASS_ENV`.

Everything else is dropped: the git provider tokens PR-Agent uses (`GITHUB_TOKEN`, `GITHUB__USER_TOKEN`, `GITLAB__PERSONAL_ACCESS_TOKEN`, `CI_JOB_TOKEN` and the rest) and the credentials of the other adapters.

`HOME` stays because the CLIs keep their login state there. An adapter with tool access can therefore read files under `HOME`, including its own saved login. R10 and the trust guidance under [Security model](#security-model) address that.

### Run modes

- **Local.** `uv tool install pr-agent-cli-handlers` puts `pr-agent-cli-handlers` on `PATH` (PR-Agent comes as a dependency). It uses the CLIs already installed and logged in. `CONFIG__GIT_PROVIDER=local` reviews a branch before it is pushed.
- **GitHub Actions.** A composite action (`action.yml` at the repository root):
  1. set up Python 3.12
  2. `pip install pr-agent-cli-handlers==<version>`
  3. install the selected CLI with its official installer, pinned by default and `latest` only on request
  4. run `pr-agent-cli-handlers action`

  Inputs: handler, CLI version, model. Credentials come from secrets through `env`. The documented triggers are `pull_request` and `issue_comment`, so fork pull requests receive no secrets and are skipped. `pull_request_target` is documented as an explicit opt-in: the action never checks out pull request code, but a fork's diff can still carry prompt-injection text.
- **GitLab pipelines.** A versioned template (`templates/gitlab-ci.yml`), usable with `include: remote:` or copied. It runs on `node:24-trixie` for `merge_request_event` (Node for the npm-installed CLIs), installs uv, which provides Python 3.12, then installs the package and the selected CLI, and runs `describe`, `review` and `improve` against `$CI_MERGE_REQUEST_PROJECT_URL/merge_requests/$CI_MERGE_REQUEST_IID`, exactly as PR-Agent's own pipeline mode does.

### Credentials and compliance

API keys are the documented default. A subscription login is documented for runs made by the person who owns it, with the vendor's own words on where it is expected, so the reader can judge their case against the terms rather than against this package's summary of them.

| CLI | API key (default) | Subscription |
|---|---|---|
| Claude Code | `ANTHROPIC_API_KEY`; Bedrock and Vertex through their own variables | `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` (Pro, Max, Team, Enterprise); documented by Anthropic for CI pipelines and scripts, tied to the subscription of the person who ran the command |
| Codex | `OPENAI_API_KEY` or `CODEX_API_KEY` | `codex login` with a ChatGPT account; documented by OpenAI for automation only through Enterprise access tokens on trusted, private runners, or a copied `~/.codex/auth.json` treated like a password |
| `agy` | `GEMINI_API_KEY` | cached Google-account login; experimental until P6 |

Anthropic's [legal and compliance page for Claude Code](https://code.claude.com/docs/en/legal-and-compliance) (read 2026-09-23, re-read 2026-10-17) splits into rules the package satisfies by construction and rules only the user's own situation can satisfy.

By construction:

- The page does not prevent "an end user from signing in to the unmodified Claude Code binary with their own Claude subscription". The package runs the published binary unmodified and leaves sign-in to Anthropic's own flow.
- "Developers may not collect, store, or intermediate Claude.ai credentials or session tokens". The package never reads a credential. It only passes allowlisted variables through to the child process.
- "Customers may not pay for, resell, or intermediate Claude usage on their end users' behalf". The package is self-hosted only, with no hosted mode, and bills nothing to anyone.
- The Claude Code name and logo may not be part of a product name. The package name avoids it, and the documentation states that the project is not affiliated with Anthropic, OpenAI or Google.

Left to the user, and said so in the README:

- OAuth login "is designed to support ordinary use of Claude Code and other native Anthropic applications", and "advertised usage limits for Pro and Max plans assume ordinary, individual usage". A developer reviewing their own branch is the case the documentation describes; a team repository is not, and the documentation points it to API keys with spending limits.
- Developers "building products or services that interact with Claude's capabilities" should use API key authentication and may not "route requests through Free, Pro, or Max plan credentials on behalf of their users". The package is such a product in the broad reading and a wrapper around the user's own binary and login in the narrow one. The page does not settle which applies, and "Anthropic reserves the right to take measures to enforce these restrictions and may do so without prior notice", so the README quotes both sentences and defaults every example to an API key.
- Anthropic's own [GitHub Actions page](https://code.claude.com/docs/en/github-actions) accepts `CLAUDE_CODE_OAUTH_TOKEN` and advises an API key for a secret shared across repositories, "since an OAuth token is tied to the subscription of the person who ran `claude setup-token`". The README repeats that boundary.

OpenAI's [Codex authentication page](https://developers.openai.com/codex/auth) (read 2026-10-17) says: "Use API key authentication for programmatic Codex CLI workflows, such as CI/CD jobs. Don't expose Codex execution in untrusted or public environments." ChatGPT login for automation appears only as Enterprise access tokens "intended for trusted scripts, schedulers, and private CI runners" and as a copied `auth.json` fallback for headless machines. The page does not use the word experimental, so the documentation no longer does either; it reports what OpenAI documents.

### Security model

| Threat | Vector | Mitigation |
|---|---|---|
| Credential exfiltration through review text | Prompt injection in the diff asks the agent to print its environment or read a credential file, and the response is posted to the pull request | Claude Code runs with tools off; Codex runs with its tool features switched off (P4). The child environment is allowlisted (R9). Responses are redacted (R10). `agy` keeps tool access, web search included (P3, P4), and is not selectable |
| Repository configuration steering the CLI | `.pr_agent.toml` in the pull request | Handler settings are read from the environment only (R6). Model names are validated (R7) |
| Secrets in fork pipelines | CI trigger choice | The documented triggers are `pull_request` and `issue_comment`, plus GitLab masked variables (hidden where GitLab offers it), with the trade-off of protecting them documented. Running parent pipelines for fork merge requests is warned against |
| Supply chain of the CLI | Installer fetched at job start | Versions are pinned by default, and Claude Code runs with `DISABLE_AUTOUPDATER=1` so it cannot update itself between calls |
| Subscription token misuse | A leaked token cannot be scoped or capped | Documentation recommends API keys with spending limits for shared repositories |
| Process list exposure | The system prompt is an argument for Codex | Accepted. The system prompt is PR-Agent's template plus pull request metadata; credentials never appear in arguments. Claude Code reads it from a file only the user can read |

## Testing

- **Unit tests** (pytest, no real CLI, R15):
  - the handler tests carried over from the branch, adjusted to environment variables
  - activation: a real seam check on the installed PR-Agent; a clear exit on a stand-in class whose constructor lacks the default; default replacement on all listed constructors; argument pass-through to `pr_agent.cli.run`; exit before start on an invalid `PR_AGENT_CLI_HANDLER`
  - security: sentinel values in `GITHUB_TOKEN`, `GITLAB__PERSONAL_ACCESS_TOKEN`, `CI_JOB_TOKEN` and the other adapters' credential variables never reach the child environment, logs or error messages; the adapter's own credential variables do; a response containing a sentinel value is redacted; invalid model names are rejected
- **Adapter contract tests:** a fake executable per CLI placed on `PATH` records its arguments, its standard input and the content of the file passed with `--system-prompt-file` while the call runs, and replays recorded output, including error envelopes and every `agy` status value.
- **Live smoke test** (`scripts/smoke`, manual): runs `review` through each installed CLI against three small sample diffs in PR-Agent's plain-diff mode (`--diff-file`, with `--json-output` as the parse check). Run before every release.
- **Lint:** Ruff with PR-Agent's rules (E, F, B, I; 120 columns), so the code stays portable back to PR-Agent.

## Compatibility with upstream

- CI runs on every push against the latest `pr-agent` release, on Python 3.12 and 3.13.
- A weekly scheduled job installs PR-Agent from upstream `main` and runs the suite plus a syntax-tree scan. The scan lists every `ai_handler` default of `LiteLLMAIHandler` and every direct `LiteLLMAIHandler()` construction, and fails when the list differs from the table under [Activation](#activation).
- If upstream adopts `config.ai_handler` or a `register_ai_handler` hook, activation switches to it and default replacement is removed. The adapters stay the same.

## Release

- Semantic versioning from 0.1.0, with a `CHANGELOG.md`.
- A tag triggers a GitHub Actions workflow that publishes to PyPI through trusted publishing (OIDC); no PyPI token is stored.
- The composite action and the GitLab template are referenced by the same tag.
- The README covers installation on macOS, Linux, Windows and WSL, the credentials table, the security model and the compliance notes. Native Windows is not supported in 0.1.0 and WSL is; the README's Windows row says so.

## Probes

Probes are short throwaway scripts run against real CLIs and logins before the implementation plan is final. A failed probe marks a path unsupported or experimental in the documentation; it does not block the first release.

| Id | Question | Pass condition | Result (2026-09-23) |
|---|---|---|---|
| P1 | Does `agy` finish when started in its own session with piped standard input and output and no terminal ([#318](https://github.com/google-antigravity/antigravity-cli/issues/318) was reproduced on Linux 1.2.3 on 2026-09-15)? | Ten consecutive runs on the current release exit within the timeout | Pass on 1.2.9: ten of ten succeeded, 5 to 35 seconds each |
| P2 | Does `agy` take the prompt from standard input and return a parseable result? What do `usage` fields mean? | Result parses; token fields mapped | Pass with the stream-json form documented above; `-p` cannot read standard input |
| P3 | Does PR-Agent's `review` output, produced by `agy` without system-prompt control, parse as PR-Agent expects? | Three sample diffs produce parseable reviews | Fail on 1.2.9 (2026-09-24). With the default effort all three samples were rejected (`--effort` conflicts with the effort in the model name). Without it, 2 of 7 runs produced a review, 3 ended in tool calls with an empty `SUCCESS` result, and 2 hit upstream 503s. The adapter is not selectable |
| P4 | Can Codex and `agy` run headless with their shell and file tools disabled? | A documented setting disables them; if none exists, the CLI is documented as for trusted repositories only | Codex 0.156.1: pass through `features.*=false`. `agy` 1.2.9: fail, it read a token file outside its working directory with `--sandbox` |
| P5 | Does a saved Codex ChatGPT login, provided as a CI secret file, keep working across fresh jobs after token refreshes? | Five fresh jobs over two days succeed | Pending, after release |
| P6 | The same question for `agy`'s cached Google-account credentials | Five fresh jobs over two days succeed | Pending, after release |

## Risks

- **Upstream refactors the constructors**, for example with the runtime from Discussion #3147. The seam check fails loudly and the weekly job warns a release ahead. The long-term fix is an upstream hook.
- **Vendor terms on subscription use.** Anthropic's terms already contain a sentence that can be read against a third-party tool routing requests through a subscription (see Credentials and compliance), and enforcement may come without notice and would fall on the user's account, not on the package. The package works with API keys regardless, every example defaults to one, and the subscription paths are documented, not required. The upstream maintainer declined the same handlers in core on 2026-10-16 for this reason.
- **`agy` maturity:** open headless issues ([#548](https://github.com/google-antigravity/antigravity-cli/issues/548), and [#781](https://github.com/google-antigravity/antigravity-cli/issues/781) reporting credential leaks through shell output). The adapter becomes selectable only if P1 to P3 pass on a current release, and stays marked experimental. It failed P3 on 1.2.9.
- **Output quality with CLI models:** PR-Agent's prompts were tuned against API models. The live smoke test checks that responses still parse; review quality is judged by use.

## Sources

All read on 2026-09-23 unless noted.

- [The-PR-Agent/pr-agent#3640](https://github.com/The-PR-Agent/pr-agent/issues/3640) (re-read 2026-10-17, after it was closed) and [Discussion #3147](https://github.com/The-PR-Agent/pr-agent/discussions/3147)
- PR-Agent 0.46.0 on [PyPI](https://pypi.org/project/pr-agent/) and its source at tag `v0.46.0` (`1d01f24f`), and 0.48.0 installed and scanned on 2026-10-17
- [Claude Code legal and compliance](https://code.claude.com/docs/en/legal-and-compliance) (re-read 2026-10-17), [Claude Code authentication](https://code.claude.com/docs/en/authentication) and [Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions) (both 2026-10-17)
- [Codex authentication](https://developers.openai.com/codex/auth) (2026-10-17)
- [Antigravity CLI headless mode](https://antigravity.google/docs/cli/headless/) and the [antigravity-cli issue tracker](https://github.com/google-antigravity/antigravity-cli/issues)
- [alibaba/open-code-review](https://github.com/alibaba/open-code-review), its [CI integration docs](https://github.com/alibaba/open-code-review/blob/main/pages/src/content/docs/en/integrations/ci.md) and [delegation mode docs](https://github.com/alibaba/open-code-review/blob/main/pages/src/content/docs/en/integrations/delegate.md)
- [Nikita-Filonov/ai-review](https://github.com/Nikita-Filonov/ai-review)
