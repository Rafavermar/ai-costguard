# AI Cost Guard Runbook

This runbook is for teammates who want to install, validate, operate, and remove Cost Guard safely.

## Install

```bash
pip install -e .[dev]
```

For an end-user machine:

```bash
pipx install git+https://github.com/your-org/ai-costguard.git
```

## setup

Creates Cost Guard home, `.env`, `settings.yaml`, SQLite, rules, hooks, safe commands, logs, cache folders, and Claude Code settings when enabled.

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

Shows whether Headroom is available and enabled.

## headroom enable

```bash
costguard headroom enable
```

If missing:

```bash
pip install "ai-costguard[headroom]"
```

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

Stops the proxy, restores Claude Code settings from backup when possible, removes only Cost Guard fragments otherwise, removes autostart scaffolding if present, and keeps Cost Guard home by default.

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
