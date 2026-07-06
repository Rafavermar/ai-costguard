# AI Cost Guard

AI Cost Guard is a local-first AI gateway/middleware for developers using coding agents in VS Code, mainly Cline and Claude Code.

Technically, it is a local wrapper around model traffic and tool usage. It sits between the local coding agent and your configured upstream model provider, then applies budget checks, rule-based command guardrails, output limits, model aliases, and SQLite usage accounting before forwarding allowed requests.

In practical terms, it is a **local cost, safety, and usage-efficiency control layer for AI coding agents**. It gives teams a lightweight way to observe agent usage, estimate spend, prevent obvious secret leaks, reduce noisy tool output, and keep an easy rollback path for developer machines.

It is not a full agent, model provider, cloud service, Docker stack, Postgres service, VS Code extension, or magic optimizer. The package is intentionally small: a CLI, a localhost proxy, editable rules, optional Claude Code hooks, Cline configuration text, and local storage under `COSTGUARD_HOME`.

![AI Cost Guard architecture cover](docs/assets/ai-costguard-architecture-cover.png)

```text
VS Code
  Cline                -> http://127.0.0.1:4040/v1 -> Cost Guard -> OpenAI-compatible upstream
  Claude Code path     -> http://127.0.0.1:4040    -> Cost Guard -> Anthropic-compatible upstream
```

## At A Glance

- Local middleware: runs on the developer machine and forwards to the upstream provider you configure.
- Plug-and-play CLI: `setup`, `doctor`, `status`, `rules`, `budget`, `usage`, and `uninstall`.
- Reversible install: backs up Claude Code settings before adding Cost Guard and restores them on uninstall.
- Local budget store: uses SQLite in `COSTGUARD_HOME`, with optional model pricing from a configured catalog endpoint.
- Repo-safe by default: does not modify client repositories unless `costguard attach` is explicitly run.
- Editable rules: YAML rules can be reviewed and changed without changing Python code.
- Metadata-only logging: prompts and responses are not stored by default.

## What Problem It Solves

AI coding agents are powerful, but they can be hard to operate responsibly on a work laptop:

- Usage is often invisible until the provider bill or quota error appears.
- Long context, full diffs, recursive scans, and huge logs can waste tokens.
- Agents may accidentally request `.env`, keys, tokens, state files, or sensitive terminal output.
- Corporate AI gateways may enforce quotas or secret filters that are hard to distinguish from local budget issues.
- Setup and rollback should be safe for teammates who just want to try the tool.

Cost Guard addresses that narrow operational gap. It does not make the model smarter, but it makes agent usage more observable, more constrained, and easier to reason about.

## Monitoring And Usage Improvement

Cost Guard helps monitor and improve usage efficiency through local controls. This is about reducing avoidable token waste and operational surprises; it is not a promise of lower model latency or better model reasoning.

| Capability | What You Get |
| --- | --- |
| Usage visibility | `costguard usage today/month` shows requests, estimated tokens, estimated cost, top model, rule hits, budget blocks, security blocks, output truncation, and Headroom compression evidence. |
| Budget control | Daily/monthly budget modes can warn, block premium models, or block all new calls. |
| Real pricing support | Optional `costguard pricing refresh` can cache model prices from a company/provider catalog instead of relying on fallback estimates. |
| Basic response cache | Optional exact-match cache can avoid repeat upstream calls when `basic` mode and local content storage are explicitly enabled. |
| Output reduction | Rules rewrite noisy commands such as full `git diff` or `find .`; output limits truncate oversized responses. |
| Secret guardrails | Default rules block `.env`, key-like files, Terraform state/vars, and secret-like payloads. |
| Debug clarity | Docs distinguish local Cost Guard budget decisions from upstream quota errors such as HTTP 429. |
| Local audit trail | SQLite stores metadata by default, not prompt/response content. |
| Optional Headroom compression | When a compatible Headroom adapter is installed and enabled, the proxy transforms request payloads before budget checks and upstream forwarding. |

Headroom observability is metadata-only. `usage today` can show `headroom_applied_count`, before/after input size, estimated tokens saved, and reduction ratio without storing prompt or response content.

The improvement loop is deliberately simple: inspect usage, identify noisy patterns, tune YAML rules/budgets/model aliases, refresh pricing when available, and rerun. It is an operating guardrail, not an autonomous optimization system.

## Core Components

These pieces are installed by `costguard setup` and are expected to work in the base solution:

| Component | Purpose |
| --- | --- |
| CLI | Runs setup, validation, status, budget, rules, usage, cache, Headroom status, and uninstall commands. |
| Local proxy | Provides `127.0.0.1:4040` for model traffic and forwards allowed requests to configured upstreams. |
| Config home | Stores all Cost Guard state under `COSTGUARD_HOME` or `~/.costguard` by default. |
| Claude home override | Uses `COSTGUARD_CLAUDE_HOME` instead of `~/.claude` when set, which is essential for safe smoke tests. |
| `.env` | Holds upstream base URLs, model names, local proxy key, and runtime flags. |
| `settings.yaml` | Holds tool selection, active model alias, budget mode, cache mode, and other local settings. |
| Rules | YAML files for blocked paths, blocked commands, command rewrites, log handling, and output limits. |
| Safe commands | Helper scripts such as `short-diff`, `safe-grep`, `summarize-log`, and `test-failures-only`. |
| SQLite store | Local `costguard.db` for usage metadata, budget checks, and audit events. |
| Pricing | Uses local fallback estimates by default; can refresh model pricing from a configured provider catalog. |
| Doctor checks | Validates required files, rules, hooks, safe commands, budgets, and proxy health. |
| Uninstall | Stops the proxy, restores Claude Code settings from a clean backup when available, and removes Cost Guard fragments otherwise. |

## Tool Integrations

These integrations are part of the base package, but they are only activated according to `--tool` and user configuration:

| Integration | How It Works |
| --- | --- |
| Cline | `costguard cline-config` prints OpenAI-compatible settings to paste into Cline. Cline is not edited automatically. |
| Claude Code | `setup --tool claude-code` or `setup --tool both` merges Cost Guard env vars and hooks into Claude Code `settings.json` after creating a backup. It sets `ANTHROPIC_BASE_URL` to the local proxy and `ANTHROPIC_MODEL` to `cg-active`. Local setup, backup, restore, hooks, alias routing, Anthropic headers, and streaming proxy behavior are covered by tests; real end-to-end validation requires a licensed user/key. |
| Model aliases | `cg-active` follows the currently selected category; `cg-cheap`, `cg-standard`, and `cg-strong` are fixed categories mapped locally in `.env`. |
| Hooks | Claude Code `PreToolUse` can block or rewrite risky/noisy tool calls; `PostToolUse` records local metadata. |

Model aliases are intentionally category-based, not provider-based. Each user or company can point `OPENAI_MODEL_CHEAP`, `OPENAI_MODEL_STANDARD`, `OPENAI_MODEL_STRONG`, and their Anthropic-compatible equivalents to the real model IDs approved in that environment. Configure Cline or Claude Code with `cg-active` if you want `costguard use cheap|standard|strong` to switch routing without editing the client again; configure a fixed alias such as `cg-standard` if you want a client pinned.

## Optional Components

These pieces are available but disabled or opt-in by default:

| Component | Default | Purpose |
| --- | --- | --- |
| Cache | Disabled | Basic exact-match response cache is functional but opt-in; semantic/vector mode is scaffolded for a future embeddings design. |
| Headroom | Disabled | Optional request compression via `headroom-ai` in library mode. Cost Guard calls `headroom.compress(messages, model=...)` when installed and enabled. |
| Pricing refresh | Not run | `costguard pricing refresh` reads `COSTGUARD_PRICING_URL` and caches provider model prices locally. |
| Project attach | Not run | `costguard attach` writes project-local Claude metadata only when explicitly requested. |
| Purge uninstall | Not run | `costguard uninstall --purge --yes` deletes `COSTGUARD_HOME`; plain uninstall keeps it. |
| Non-local bind host | Not used | The proxy defaults to `127.0.0.1` and warns if another host is selected. |
| Content logging | Disabled | Metadata is logged by default; prompt/response content is not stored unless explicitly enabled. |

`OPENAI_UPSTREAM_BASE_URL` and `ANTHROPIC_UPSTREAM_BASE_URL` are inference endpoints used to call models. `COSTGUARD_PRICING_URL` is a separate catalog endpoint used only to fetch model prices. A company may use the same API key for both, or provide different keys; configure that locally in `.env`.

Cache defaults are intentionally conservative:

```text
COSTGUARD_CACHE_MODE=disabled
COSTGUARD_CACHE_STORE_CONTENT=false
COSTGUARD_CACHE_MAX_ENTRIES=1000
COSTGUARD_CACHE_MAX_SIZE_MB=100
COSTGUARD_CACHE_EVICTION_POLICY=lru
```

`basic` response cache has been validated with direct identical proxy requests: first request is a miss, second identical request is a hit. Do not use Cline as the first cache test because it may add task history, tool metadata, or small request differences that change the cache key.

## Support Status

Supported and validated today:

- Cline + OpenAI-compatible upstream through Cost Guard.
- Claude-family models through Cline when the corporate/provider gateway exposes them through an OpenAI-compatible API.
- `cg-active` dynamic routing and fixed aliases `cg-cheap`, `cg-standard`, `cg-strong`.
- Pricing refresh/cache, budget/usage, rules, output limits, and basic exact-match response cache.

Ready for real Claude Code validation:

- Claude Code through the Anthropic-compatible gateway path. Cost Guard exposes `/v1/messages`, forwards Claude Code/Anthropic headers, supports SSE streaming requests, maps `cg-active`, and records usage/budget metadata. Setup/backup/uninstall and proxy behavior are tested with mocks; a real smoke still needs a licensed Claude Code user and an Anthropic-compatible upstream key.

Experimental:

- Headroom savings evidence, semantic/vector cache, and the official Claude Code VS Code plugin smoke. The plugin is expected to use the same local Anthropic-compatible gateway when it honors Claude Code settings, but it should not be presented as fully validated until a licensed user confirms traffic reaches Cost Guard and usage is recorded.

Recommended enterprise path for beta: use Cline + Cost Guard first because it is already smoke-tested on a work PC. Then validate Claude Code with the same local proxy pattern when an Anthropic-compatible upstream and licensed Claude Code user are available.

## What It Does

- Runs a localhost proxy on `127.0.0.1:4040`.
- Supports Cline via OpenAI-compatible `/v1/chat/completions`.
- Implements an Anthropic-compatible `/v1/messages` proxy route with streaming support for Claude Code validation.
- Maps model aliases: dynamic `cg-active`, plus fixed `cg-cheap`, `cg-standard`, and `cg-strong`.
- Enforces daily/monthly budgets with `warn`, `block-premium`, or `block-all`.
- Blocks secret-like paths and commands such as `cat .env`.
- Rewrites noisy commands such as full `git diff` and `find .`.
- Logs usage metadata to local SQLite without prompts or responses by default.
- Can serve repeated identical requests from a local exact-match cache when `basic` mode and content storage are explicitly enabled.
- Installs reversible Claude Code hooks and safe commands.
- Helps reduce avoidable token usage by rewriting noisy commands and limiting oversized outputs.
- Provides a simple feedback loop to tune usage patterns with `usage`, `budget`, `rules`, and optional `pricing` data.
- Separates local budget decisions from upstream provider quota/rate-limit errors.
- Applies optional Headroom request compression when a compatible adapter is installed and enabled.

## What It Does Not Do

- It does not replace Cline, Claude Code, or your corporate GenAI backends.
- It does not guarantee lower cost by itself; savings depend on rules, model choices, context hygiene, and team behavior.
- It does not make the upstream model faster or more accurate.
- It does not bypass corporate quotas, rate limits, or secret filters.
- It does not require Docker, Kubernetes, Postgres, or a cloud dashboard.
- It does not expose the proxy outside localhost unless you explicitly choose another host.
- It does not modify project repos unless you run `costguard attach`.
- It does not store real API keys in Git.
- It does not store prompt/response content unless response cache content storage is explicitly enabled in local `.env`.
- It does not require Headroom for the base product; install `ai-costguard[headroom]` or `headroom-ai` separately to enable it.
- It does not apply Headroom compression unless a compatible adapter is installed and explicitly enabled.
- It does not provide production semantic/vector cache yet; that remains experimental until embeddings, vector storage, similarity thresholds, and tests are implemented.
- It does not claim the official Claude Code VS Code plugin is fully validated until a licensed user confirms custom endpoint/proxy behavior end to end.

## Install

From a GitHub repo:

```bash
pipx install git+https://github.com/<user-or-org>/ai-costguard.git
```

For local development:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

## Quickstart

```bash
costguard setup --tool both --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard doctor
costguard start
costguard cline-config
```

Then configure upstream endpoints and model names in:

```text
~/.costguard/.env
```

Set `COSTGUARD_HOME` and `COSTGUARD_CLAUDE_HOME` before setup if you want all files somewhere else. This is recommended for tests, demos, and shared internal validation.

## Cline Configuration

Run:

```bash
costguard cline-config
```

Paste the printed values into Cline:

```text
Provider: OpenAI Compatible
Base URL: http://127.0.0.1:4040/v1
API Key: sk-costguard-local
Model ID: cg-active
```

Use `cg-active` for dynamic model switching. Fixed alternatives are `cg-cheap`, `cg-standard`, and `cg-strong`.

## Useful Commands

```bash
costguard status
costguard doctor
costguard use cheap|standard|strong
costguard budget status
costguard pricing status
costguard pricing configure --endpoint <pricing-catalog-url> --api-key-env PRICING_API_KEY --auth-header x-api-key
costguard pricing refresh
costguard budget set --daily 5 --monthly 100
costguard budget mode warn|block-premium|block-all
costguard rules test "cat .env"
costguard rules test "git diff"
costguard usage today
costguard cache status
costguard headroom status
costguard uninstall
```

## Safe Local Development

Use isolated paths so setup and uninstall never touch your real home configuration:

```powershell
$env:COSTGUARD_HOME = "$(Get-Location)\.tmp\costguard"
$env:COSTGUARD_CLAUDE_HOME = "$(Get-Location)\.tmp\claude"
costguard setup --tool both --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard doctor
costguard rules test "cat .env"
costguard uninstall --yes
```

## Documentation

- `docs/START_HERE.md`: first page for humans and agents choosing the right flow.
- `docs/RUNBOOK.md`: command-first operating guide.
- `docs/WORK_PC_UPDATE.md`: command-first work-PC update procedure for corporate forks using `uv`.
- `docs/ARCHITECTURE.md`: local proxy architecture and data flow.
- `docs/SECURITY.md`: security model and local data handling.
- `docs/TROUBLESHOOTING.md`: common failures and fixes.
- `docs/prompts/work-pc-validation-prompt.es.md`: reusable Spanish prompt for controlled work-PC validation with Cline.
- `config/pricing.example.yaml`: example model pricing catalog configuration without secrets.

## License

MIT. See `LICENSE`.
