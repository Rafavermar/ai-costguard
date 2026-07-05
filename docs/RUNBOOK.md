# AI Cost Guard Runbook

This runbook is for teammates who want to install, validate, operate, and remove Cost Guard safely.

AI Cost Guard is a local AI gateway/middleware. It runs on your machine, receives Cline or Claude Code traffic, applies local rules and budget checks, then forwards allowed requests to the upstream provider configured in `.env`.

## Safe Operating Flow

1. Install the package.
2. Run `costguard setup`.
3. Run `costguard doctor`.
4. Configure Cline with `costguard cline-config` or let setup merge Claude Code settings.
5. Use `costguard status`, `costguard budget status`, and `costguard usage today` to inspect behavior.
6. Run `costguard uninstall` to restore Claude Code settings and remove Cost Guard fragments.

For tests and demos, always set:

```bash
export COSTGUARD_HOME="$(pwd)/.tmp/costguard"
export COSTGUARD_CLAUDE_HOME="$(pwd)/.tmp/claude"
```

PowerShell:

```powershell
$env:COSTGUARD_HOME = "$(Get-Location)\.tmp\costguard"
$env:COSTGUARD_CLAUDE_HOME = "$(Get-Location)\.tmp\claude"
```

## Reusable Work-PC Prompt

For a controlled validation on a work laptop with Cline, use the reusable Spanish prompt in:

```text
docs/prompts/work-pc-validation-prompt.es.md
```

It asks the assistant to run the isolated smoke first, avoid printing secrets, install `costguard` as a global command with `uv tool install --editable ... --link-mode=copy` when available, configure only Cline before Claude Code, and document Windows PATH or OneDrive issues.

## Work-PC Update Procedure

For updating an existing corporate work-PC checkout from a company GitHub fork without touching client repositories or consuming LLM tokens, use:

```text
docs/WORK_PC_UPDATE.md
```

It covers Sync fork from GitHub web, `git pull --ff-only`, stopping CostGuard before recreating `.venv`, `uv sync --extra dev --extra headroom`, and offline validations.

## Install

```bash
pip install -e .[dev]
```

For an end-user machine:

```bash
pipx install git+https://github.com/your-org/ai-costguard.git
```

On Windows work laptops where `uv` is available, a practical local install from the repo is:

```powershell
uv venv .venv --python 3.14
uv pip install -e ".[dev]" --python .venv\Scripts\python.exe --link-mode=copy
uv tool install --editable "." --link-mode=copy
costguard --help
```

Use a Python version `>=3.10` that exists on the machine. Keep `--link-mode=copy` when the repo is under OneDrive.

## setup

Creates Cost Guard home, `.env`, `settings.yaml`, SQLite, rules, hooks, safe commands, logs, cache folders, and Claude Code settings when enabled.

When Claude Code is enabled, the first setup on a real workstation backs up the current `settings.json` before adding Cost Guard env vars and hooks. Re-running setup does not replace that clean pre-Cost-Guard backup with an already instrumented file.

```bash
costguard setup
costguard setup --tool both --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard setup --dry-run
```

## start

Starts the local proxy.

```bash
costguard start
costguard start --host 127.0.0.1 --port 4040
```

The default bind address is `127.0.0.1`. Cost Guard warns if another host is used.

## stop

Stops the proxy if it was started by Cost Guard and a pid file is available.

```bash
costguard stop
```

## status

Shows proxy address, tools, active model, budget, cache, Headroom, config path, SQLite path, and log path.

```bash
costguard status
```

## doctor

Validates local installation and prints OK, WARN, and ERROR checks.

```bash
costguard doctor
```

It checks home, `.env`, `settings.yaml`, SQLite, hooks, safe commands, rules, Claude Code settings, Cline instructions, upstream variables, budgets, script permissions, and proxy health.

## cline-config

Prints exactly what to paste into Cline.

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

## use

Changes the active model alias.

```bash
costguard use cheap
costguard use standard
costguard use strong
costguard use sonnet
```

When Claude Code is configured, `ANTHROPIC_MODEL` is updated too.

## budget status

Shows daily and monthly usage, limits, remaining budget, mode, and current action.

```bash
costguard budget status
```

## budget set

Updates limits.

```bash
costguard budget set --daily 5
costguard budget set --monthly 100
costguard budget set --daily 10 --monthly 200
```

## budget mode

Sets behavior after budget is reached.

```bash
costguard budget mode warn
costguard budget mode block-premium
costguard budget mode block-all
```

Modes:

- `warn`: warn but allow.
- `block-premium`: block `cg-strong` and `cg-sonnet`.
- `block-all`: block new calls.

## pricing status

Shows whether a provider pricing endpoint is configured and how many model prices are cached locally.

```bash
costguard pricing status
```

By default, Cost Guard uses simple local fallback estimates from `settings.yaml`. For a real corporate deployment, configure a model pricing endpoint in `.env` and refresh the local cache.

## pricing refresh

Fetches model pricing from the configured endpoint and writes local pricing data to `config/pricing.yaml`.

```bash
costguard pricing refresh
costguard pricing refresh --dry-run
costguard pricing configure --endpoint https://models.example.com/v1/models --api-key-env PRICING_API_KEY --auth-header x-api-key
costguard pricing refresh --endpoint https://models.example.com/v1/models --api-key-env PRICING_API_KEY --auth-header x-api-key
```

Expected `.env` variables:

```text
COSTGUARD_PRICING_URL=
COSTGUARD_PRICING_API_KEY_ENV=
COSTGUARD_PRICING_API_KEY=
COSTGUARD_PRICING_AUTH_HEADER=x-api-key
COSTGUARD_PRICING_AUTH_SCHEME=
```

For corporate validation, prefer `--api-key-env` or `COSTGUARD_PRICING_API_KEY_ENV` so the real key stays in an environment variable, not in Git, shell history, logs, or screenshots.

Example PowerShell:

```powershell
$env:PRICING_API_KEY = "<REDACTED>"
costguard pricing configure --endpoint https://models.example.com/v1/models --api-key-env PRICING_API_KEY --auth-header x-api-key
costguard pricing refresh --dry-run
costguard pricing refresh
```

Use your company's model catalog endpoint. Do not use an OpenAI-compatible inference endpoint as the pricing source.

The endpoint should return a JSON model catalog. Cost Guard recognizes generic fields such as `name`, `systemName`, `inputPrice`, `outputPrice`, `cachedTokenReadPrice`, and `cachedTokenCreationPrice`. Prices are treated as cost per 1,000,000 tokens and are calculated separately for input and output tokens.

Do not commit API keys or other secrets. Keep keys in local environment variables or the local `.env`; prefer `--api-key-env` for work-PC validation.

`pricing refresh` does not call chat/completions and does not consume LLM tokens. It fetches a model catalog, writes the raw response to `cache/models.json`, and writes normalized prices to `config/pricing.yaml`. If no catalog is configured or available, Cost Guard falls back to local estimates from `settings.yaml`.

Cost Guard budget is a local control. It is separate from upstream provider quotas. If the upstream returns an error such as `429`, that is a provider quota/rate-limit response even when `costguard budget status` shows `mode=warn` and `action=allow`.

## rules list

Shows active rules and origin.

```bash
costguard rules list
```

Origins are default, user, and project.

## rules edit

Opens `rules/user.yaml` in the default editor. If no editor is configured, prints the path.

```bash
costguard rules edit
```

## rules test

Evaluates a command without executing it.

```bash
costguard rules test "cat .env"
costguard rules test "git diff"
costguard rules test "find ."
```

Output is ALLOW, BLOCK, or REWRITE with a reason.

## usage today

Shows today's requests, estimated tokens, estimated cost, most used model, rules triggered, reduced outputs, and security blocks.

```bash
costguard usage today
```

## usage month

Same view for the current month.

```bash
costguard usage month
```

## cache status

Shows disabled, basic, or semantic mode, cache path, entries, and approximate size.

```bash
costguard cache status
```

## cache enable

Enables optional local cache.

```bash
costguard cache enable --mode basic
costguard cache enable --mode semantic
```

Semantic mode is scaffolded for a future vector engine and is disabled by default.

## cache disable

```bash
costguard cache disable
```

## cache clear

```bash
costguard cache clear
```

## headroom status

```bash
costguard headroom status
```

Shows whether a compatible Headroom package is available, whether the local enable flag is set, and which adapter function will be used.

## headroom enable

```bash
costguard headroom enable
```

If missing:

```bash
pip install "ai-costguard[headroom]"
```

or install Headroom directly into the same Python environment as Cost Guard:

```bash
pip install headroom-ai
```

`costguard headroom enable` requires an importable Python module named `headroom` exposing the official library function:

- `compress`

For custom adapters, Cost Guard also accepts:

- `compress_payload`
- `compress_request`
- `transform_payload`
- `apply`

Once enabled, Cost Guard applies Headroom before budget checks and upstream forwarding. Use Headroom in library mode through Cost Guard first; avoid `headroom wrap cline` during initial rollout because Cost Guard already owns Cline/Claude setup, backup, and uninstall.

## headroom disable

```bash
costguard headroom disable
```

## attach

Attaches Cost Guard metadata to the current project only when explicitly requested.

```bash
costguard attach --project my-project
costguard attach --project my-project --dry-run
```

It creates `.claude/settings.local.json`, sets `COSTGUARD_PROJECT` and `COSTGUARD_REPO`, and adds the file to `.git/info/exclude` if the current directory is a Git repo. It does not modify `.gitignore`.

## uninstall

```bash
costguard uninstall
costguard uninstall --dry-run
```

Stops the proxy, restores Claude Code settings from the latest clean backup when possible, removes only Cost Guard fragments otherwise, removes Cost Guard backup files after cleanup, and keeps Cost Guard home by default.

This is the intended revert path for a teammate who tries Cost Guard on a work machine and decides not to keep it: run `costguard uninstall`, then Claude Code should be back to the settings it had before the first Cost Guard setup.

## uninstall --purge

```bash
costguard uninstall --purge --yes
```

Also deletes Cost Guard home. Confirmation is required unless `--yes` is provided.

## Safe Local Development

Never run development smoke tests against your real home directories. Use temporary paths inside the repo:

```bash
export COSTGUARD_HOME="$(pwd)/.tmp/costguard"
export COSTGUARD_CLAUDE_HOME="$(pwd)/.tmp/claude"
costguard setup --tool both --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard doctor
costguard cline-config
costguard rules test "cat .env"
costguard rules test "git diff"
costguard budget status
costguard uninstall --yes
```

PowerShell:

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
