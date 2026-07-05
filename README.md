# AI Cost Guard

AI Cost Guard is a local-first proxy and guardrail kit for reducing token usage and controlling spend when developers use coding agents in VS Code, especially Cline and Claude Code.

It does not replace Cline, Claude Code, or your corporate model backends. It sits locally between the tool and the upstream endpoint, applies cost and safety rules, and records only usage metadata by default.

```text
VS Code
  Cline       -> http://127.0.0.1:4040/v1 -> Cost Guard -> OpenAI-compatible upstream
  Claude Code -> http://127.0.0.1:4040    -> Cost Guard -> Anthropic-compatible upstream
```

## What It Solves

- Keeps agent calls behind a localhost proxy.
- Maps friendly model aliases such as `cg-standard` and `cg-sonnet`.
- Enforces daily and monthly budgets.
- Blocks secret-like file access and risky commands.
- Rewrites expensive commands such as full `git diff`.
- Limits oversized outputs where possible.
- Logs usage metadata to local SQLite, without prompts or responses by default.
- Installs reversible Claude Code hooks and safe commands.

## What It Does Not Do

- It does not replace your coding agents.
- It does not store API keys in Git.
- It does not require Docker, Kubernetes, Postgres, or cloud dashboards.
- It does not expose the proxy outside `127.0.0.1` unless you ask it to.
- It does not touch client repos unless you explicitly run `costguard attach`.

## Quickstart

```bash
pipx install git+https://github.com/your-org/ai-costguard.git
costguard setup
costguard start
costguard doctor
costguard cline-config
```

For local development in this repository, use isolated paths:

```bash
export COSTGUARD_HOME="$(pwd)/.tmp/costguard"
export COSTGUARD_CLAUDE_HOME="$(pwd)/.tmp/claude"
pip install -e .[dev]
costguard setup --tool both --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard doctor
```

PowerShell:

```powershell
$env:COSTGUARD_HOME = "$(Get-Location)\.tmp\costguard"
$env:COSTGUARD_CLAUDE_HOME = "$(Get-Location)\.tmp\claude"
pip install -e .[dev]
costguard setup --tool both --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard doctor
```

## Setup

`costguard setup` creates:

- `~/.costguard/.env`
- `~/.costguard/config/settings.yaml`
- `~/.costguard/costguard.db`
- rules, hooks, safe commands, logs, cache directories, and backups
- Claude Code settings backup and merged Cost Guard settings when Claude Code is enabled

Non-interactive example:

```bash
costguard setup --tool both --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
```

Dry run:

```bash
costguard setup --dry-run
```

## Cline

Run:

```bash
costguard cline-config
```

Paste this into Cline:

```text
Provider: OpenAI Compatible
Base URL: http://127.0.0.1:4040/v1
API Key: sk-costguard-local
Model ID: cg-standard
```

Then start the proxy:

```bash
costguard start
```

## Claude Code

`costguard setup --tool claude-code` or `--tool both` merges Cost Guard settings into Claude Code's `settings.json` and creates a backup first. Existing settings and hooks are preserved.

Cost Guard sets Claude Code to use:

```text
ANTHROPIC_BASE_URL=http://127.0.0.1:4040
ANTHROPIC_AUTH_TOKEN=sk-costguard-local
ANTHROPIC_MODEL=cg-standard
```

## Daily Use

```bash
costguard status
costguard doctor
costguard use cheap
costguard use standard
costguard use strong
costguard use sonnet
```

Model aliases:

- `cheap` -> `cg-cheap`
- `standard` -> `cg-standard`
- `strong` -> `cg-strong`
- `sonnet` -> `cg-sonnet`

## Budgets

```bash
costguard budget status
costguard budget set --daily 5
costguard budget set --monthly 100
costguard budget mode warn
costguard budget mode block-premium
costguard budget mode block-all
```

`block-premium` blocks `cg-strong` and `cg-sonnet` when budget is reached.

## Rules

```bash
costguard rules list
costguard rules test "cat .env"
costguard rules test "git diff"
costguard rules edit
```

Rules are loaded from default, user, and project sources. Project rules live at `.costguard/rules.yaml` if you create them.

## Cache

Cache is disabled by default.

```bash
costguard cache status
costguard cache enable --mode basic
costguard cache enable --mode semantic
costguard cache disable
costguard cache clear
```

The MVP stores only local metadata scaffolding. Semantic/vector cache is optional and prepared for future vector engines.

## Headroom

Headroom is optional and disabled by default.

```bash
costguard headroom status
costguard headroom enable
costguard headroom disable
```

If the optional integration is missing, install:

```bash
pip install "ai-costguard[headroom]"
```

## Usage

```bash
costguard usage today
costguard usage month
```

Usage records contain timestamps, client, model alias, upstream, estimated chars, estimated tokens, estimated cost, budget action, and security metadata. Prompts and responses are not stored by default.

## Attach A Project

`costguard attach --project <name>` creates `.claude/settings.local.json` in the current repo and adds it to `.git/info/exclude`. It does not modify `.gitignore` or source code.

```bash
costguard attach --project my-project
```

## Uninstall

```bash
costguard uninstall
```

This stops the proxy if Cost Guard started it, restores Claude Code settings from backup if available, removes only Cost Guard fragments otherwise, and keeps `~/.costguard`.

```bash
costguard uninstall --purge --yes
```

This also removes the Cost Guard home directory.

## Security

- API keys live in local `.env`, not Git.
- The proxy listens on localhost by default.
- Claude Code settings are backed up before changes.
- Content logging is disabled by default.
- Secret-like payloads and paths are blocked.
- Cache and Headroom are optional because they can introduce extra data-retention risks.

## Limitations

- Token and cost calculations are estimates unless upstream billing data is available.
- Proxy support is intentionally minimal for the MVP.
- Semantic cache is a local scaffold, not a full vector engine yet.
- Cline still needs manual settings changes.

## Troubleshooting

Start with:

```bash
costguard doctor
costguard status
```

Common fixes:

- Port busy: run `costguard start --port 4041` and update tool config.
- Missing upstream vars: edit `~/.costguard/.env`.
- Cline cannot connect: confirm Base URL is `http://127.0.0.1:4040/v1`.
- Claude Code cannot connect: inspect `~/.claude/settings.json` and run `costguard doctor`.
- Need rollback: run `costguard uninstall`.

See `docs/TROUBLESHOOTING.md` for more.
