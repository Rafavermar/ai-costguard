# AI Cost Guard Runbook

AI Cost Guard is a local AI gateway/middleware for Cline and Claude Code. It runs on the developer machine, applies local rules and budget checks, then forwards allowed requests to the configured upstream provider.

If you are not sure which procedure to run, start with `docs/START_HERE.md`.

## Golden Rules

- Use `COSTGUARD_HOME` and `COSTGUARD_CLAUDE_HOME` for tests and demos; do not touch real home config unless you mean to.
- Do not commit real endpoints, API keys, screenshots, logs, or `.env` values.
- Cost Guard does not modify client repos unless `costguard attach` is explicitly run.
- `OPENAI_UPSTREAM_BASE_URL` / `ANTHROPIC_UPSTREAM_BASE_URL` are inference endpoints; `COSTGUARD_PRICING_URL` is a separate pricing catalog endpoint.
- Provider `429` or secret-filter errors are upstream controls; Cost Guard budget is local policy.

## Safe Local Smoke

Use this before changing real workstation settings.

```powershell
$env:COSTGUARD_HOME = "$(Get-Location)\.tmp\costguard"
$env:COSTGUARD_CLAUDE_HOME = "$(Get-Location)\.tmp\claude"

costguard setup --tool both --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard doctor
costguard cline-config
costguard rules test "cat .env"
costguard rules test "git diff"
costguard budget status
costguard uninstall --yes
```

Bash equivalent:

```bash
export COSTGUARD_HOME="$(pwd)/.tmp/costguard"
export COSTGUARD_CLAUDE_HOME="$(pwd)/.tmp/claude"
```

## Install

Use `uv` on Windows work laptops, especially when the repo lives under OneDrive.

```powershell
uv venv .venv --python 3.14
uv pip install -e ".[dev]" --python .venv\Scripts\python.exe --link-mode=copy
uv tool install --editable "." --link-mode=copy
costguard --help
```

Use any installed Python `>=3.10`; keep `--link-mode=copy` for OneDrive.

## Setup

Creates Cost Guard home, `.env`, settings, SQLite, rules, hooks, safe commands, logs, cache folders, and optional Claude Code settings.

```bash
costguard setup
costguard setup --tool both --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard setup --dry-run
```

Claude Code setup creates a clean backup before merging Cost Guard settings.

## Start And Stop

Run the local proxy on localhost.

```bash
costguard start
costguard start --host 127.0.0.1 --port 4040
costguard stop
```

The default bind address is `127.0.0.1`; other hosts should be intentional.

## Cline Config

Print the values to paste into Cline.

```bash
costguard cline-config
```

Expected values:

```text
Provider: OpenAI Compatible
Base URL: http://127.0.0.1:4040/v1
API Key: sk-costguard-local
Model ID: cg-standard
```

## Daily Checks

Inspect install health, proxy state, usage, and local budget.

```bash
costguard status
costguard doctor
costguard usage today
costguard budget status
```

## Model Alias

Switch the local model category; real model IDs stay in local `.env`.

```bash
costguard use cheap
costguard use standard
costguard use strong
```

Canonical aliases are `cg-cheap`, `cg-standard`, and `cg-strong`.

## Budget

Set limits and behavior after limits are reached.

```bash
costguard budget set --daily 5 --monthly 100
costguard budget mode warn
costguard budget mode block-premium
costguard budget mode block-all
```

Modes: `warn` allows, `block-premium` blocks `cg-strong`, `block-all` blocks new calls.

## Rules

Inspect, edit, and test local command guardrails.

```bash
costguard rules list
costguard rules edit
costguard rules test "cat .env"
costguard rules test "git diff"
costguard rules test "find ."
```

Expected defaults: `.env` is blocked; full `git diff` and `find .` are rewritten to smaller commands.

## Pricing Catalog

Configure this only if your company/provider exposes a model pricing catalog.

```text
# Inference endpoint: used to call models.
OPENAI_UPSTREAM_BASE_URL=
OPENAI_UPSTREAM_API_KEY=

# Pricing catalog endpoint: used only to fetch model prices.
COSTGUARD_PRICING_URL=
COSTGUARD_PRICING_API_KEY_ENV=
COSTGUARD_PRICING_API_KEY=
COSTGUARD_PRICING_AUTH_HEADER=x-api-key
COSTGUARD_PRICING_AUTH_SCHEME=
```

If the same key works for inference and pricing:

```text
COSTGUARD_PRICING_API_KEY_ENV=OPENAI_UPSTREAM_API_KEY
```

If pricing has a separate key:

```powershell
$env:PRICING_API_KEY = "<REDACTED>"
costguard pricing configure --endpoint https://models.example.com/v1/models --api-key-env PRICING_API_KEY --auth-header x-api-key
```

Validate and cache prices locally.

```bash
costguard pricing status
costguard pricing refresh --dry-run
costguard pricing refresh
```

Do not use the inference endpoint as the pricing source; pricing refresh calls a catalog endpoint and does not consume LLM tokens.

## Cache

Manage optional local cache state.

```bash
costguard cache status
costguard cache enable --mode basic
costguard cache disable
costguard cache clear
```

Semantic mode is scaffolded for a future vector engine.

## Headroom

Optional request compression requires a compatible external package.

```bash
costguard headroom status
costguard headroom enable
costguard headroom disable
```

Install only when needed:

```bash
pip install "ai-costguard[headroom]"
```

## Attach

Attach project metadata only when explicitly requested.

```bash
costguard attach --project my-project
costguard attach --project my-project --dry-run
```

It writes `.claude/settings.local.json` and excludes it via `.git/info/exclude`; it does not edit `.gitignore`.

## Uninstall

Revert Claude Code settings and remove Cost Guard fragments.

```bash
costguard uninstall
costguard uninstall --dry-run
```

Delete Cost Guard home only when explicitly requested.

```bash
costguard uninstall --purge --yes
```

Plain uninstall keeps `COSTGUARD_HOME`; purge deletes it.

## Work-PC Guides

Use these when validating or updating a corporate laptop.

```text
docs/prompts/work-pc-validation-prompt.es.md
docs/WORK_PC_UPDATE.md
docs/TROUBLESHOOTING.md
```
