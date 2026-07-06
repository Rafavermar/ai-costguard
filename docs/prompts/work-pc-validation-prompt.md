# Prompt: Controlled Work-PC Validation

Use this prompt to install and validate `ai-costguard` on a corporate Windows laptop with Cline and, optionally, Claude Code. The goal is to avoid secrets, avoid client repositories, and avoid touching real home configuration until isolated smoke tests pass.

This prompt assumes common corporate Windows constraints: `python` may not be on `PATH`, `uv` is often the safest installer, OneDrive can break hardlinks, and the global `costguard` command should be refreshed before validation.

````text
I want to install and validate the `ai-costguard` repo on my work PC in a controlled way without exposing secrets.

Important safety rules:
- Start a new Cline task for this validation.
- Do not use Retry on an old task if a security error appears.
- Do not reuse a task that may contain credentials, tokens, API keys, `.env` content, provider configuration, terminal output with secrets, or sensitive screenshots.
- If `payload blocked by secret filter` appears, first assume accumulated agent context may be the cause.
- Before diagnosing Cost Guard, start a new task and test a minimal prompt: `Say OK`.
- Do not load `.env`, `.env.*`, key files, token files, `.cline`, `.vscode`, provider config files, or credential screenshots as agent context.
- Do not ask me to paste secrets in chat.
- Do not print real keys, tokens, endpoints, or sensitive config.
- Do not pass secrets as command arguments.
- Do not commit `.env`, logs, screenshots, cache files, or company endpoints.
- Do not modify client repositories.
- Do not touch any repo other than `ai-costguard` unless I explicitly ask.
- Do not change real Claude Code settings until I explicitly approve it.
- First validate everything with `COSTGUARD_HOME` and `COSTGUARD_CLAUDE_HOME` inside the repo.

First read:
- `README.md`
- `docs/START_HERE.md`
- `docs/RUNBOOK.md`
- `docs/WORK_PC_UPDATE.md`
- `docs/SECURITY.md`
- `docs/TROUBLESHOOTING.md`
- `pyproject.toml`

Summarize briefly:
- what Cost Guard is
- how to install it
- how Cline is configured
- how Claude Code is configured
- how uninstall and rollback work
- which local files are touched
- which components are mandatory and optional
- how to avoid accumulated Cline context problems
- how to react to `payload blocked by secret filter`

## Phase 1 - Detect Python And uv

On corporate machines, `python` may not be on `PATH`. Detect what is available before creating a virtualenv:

```powershell
where.exe python
where.exe python3
Get-Command py -ErrorAction SilentlyContinue
where.exe uv
```

If `uv` is available, use it as the recommended path.
If only `python`, `python3`, or `py` is available, use that executable directly.
Do not install or change global Python without my permission.

## Phase 2 - Create Local Environment

Recommended `uv` path:

```powershell
uv python list
uv venv .venv --python 3.14
uv pip install -e ".[dev]" --python .venv\Scripts\python.exe --link-mode=copy
```

Use any installed Python `>=3.10` if Python 3.14 is not available.
Keep `--link-mode=copy` when the repo is under OneDrive.

Fallback standard Python path:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev]
```

Run tests:

```powershell
.\.venv\Scripts\pytest.exe
```

## Phase 3 - Install Global `costguard`

Install or refresh the global CLI command:

```powershell
uv tool install --editable "." --link-mode=copy --force
costguard --help
```

If `--force` is unsupported:

```powershell
uv tool uninstall costguard
uv tool install --editable "." --link-mode=copy
costguard --help
```

Do not edit global `PATH` without my permission. If the command is not found, report where `uv` installed it.

## Phase 4 - Isolated Smoke Tests

Never run initial smoke tests against real home config. Use temporary repo-local paths:

```powershell
$env:COSTGUARD_HOME = "$(Get-Location)\.tmp\costguard"
$env:COSTGUARD_CLAUDE_HOME = "$(Get-Location)\.tmp\claude"
```

Run:

```powershell
costguard --help
costguard setup --tool both --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard doctor
costguard cline-config
costguard status
costguard rules test "cat .env"
costguard rules test "git diff"
costguard rules test "find ."
costguard budget status
costguard usage today
costguard cache status
costguard headroom status
costguard uninstall --yes
.\.venv\Scripts\pytest.exe
```

Expected:
- tests pass
- `.env` is blocked
- `git diff` and `find .` are rewritten
- setup writes only inside `.tmp`
- uninstall restores isolated Claude Code settings
- no LLM call is made

Do not use `&&` in PowerShell if it fails; run commands separately or use `;`.

## Phase 5 - Real Cline Setup

Only after isolated smoke tests pass, clear temporary variables and run real Cline setup:

```powershell
Remove-Item Env:COSTGUARD_HOME -ErrorAction SilentlyContinue
Remove-Item Env:COSTGUARD_CLAUDE_HOME -ErrorAction SilentlyContinue
costguard setup --tool cline --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
```

Do not configure Claude Code yet.

## Phase 6 - Local `.env`

Tell me which local file to edit. Do not print sensitive content.

Usually:

```text
C:\Users\<user>\.costguard\.env
```

For Cline/OpenAI-compatible inference:

```text
OPENAI_UPSTREAM_BASE_URL=<inference-base-url>
OPENAI_UPSTREAM_API_KEY=<redacted>
OPENAI_MODEL_CHEAP=<approved-cheap-model>
OPENAI_MODEL_STANDARD=<approved-standard-model>
OPENAI_MODEL_STRONG=<approved-strong-model>
```

For optional pricing catalog:

```text
COSTGUARD_PRICING_URL=<model-pricing-catalog-url>
COSTGUARD_PRICING_API_KEY_ENV=OPENAI_UPSTREAM_API_KEY
COSTGUARD_PRICING_AUTH_HEADER=x-api-key
COSTGUARD_PRICING_AUTH_SCHEME=
```

If pricing uses a separate key, use `COSTGUARD_PRICING_API_KEY_ENV=PRICING_API_KEY` and define that variable locally. Do not duplicate or print secrets.

For Claude Code/Anthropic-compatible inference, only if the provider exposes an Anthropic Messages-compatible API:

```text
ANTHROPIC_UPSTREAM_BASE_URL=<anthropic-compatible-base-url>
ANTHROPIC_UPSTREAM_API_KEY=<redacted>
ANTHROPIC_UPSTREAM_AUTH_HEADER=x-api-key
ANTHROPIC_UPSTREAM_AUTH_SCHEME=
ANTHROPIC_MODEL_CHEAP=<approved-cheap-model>
ANTHROPIC_MODEL_STANDARD=<approved-standard-model>
ANTHROPIC_MODEL_STRONG=<approved-strong-model>
```

Use `ANTHROPIC_UPSTREAM_AUTH_HEADER=Authorization` and `ANTHROPIC_UPSTREAM_AUTH_SCHEME=Bearer` only if the provider requires Bearer auth.

Never hardcode real endpoints or keys in the repo.

## Phase 7 - Post-Credential Validation

```powershell
costguard doctor
costguard status
costguard cline-config
costguard pricing status
```

If pricing is configured:

```powershell
costguard pricing refresh --dry-run
costguard pricing refresh
costguard pricing status
```

Pricing refresh must not call an LLM and must not store API keys in `config/pricing.yaml` or `cache/models.json`.

## Phase 8 - Cline Smoke

Configure Cline manually:

```text
Provider: OpenAI Compatible
Base URL: http://127.0.0.1:4040/v1
API Key: sk-costguard-local
Model ID: cg-active
```

Start Cost Guard in a dedicated terminal:

```powershell
costguard start
```

In a new Cline task, send only:

```text
Say OK
```

Then check:

```powershell
costguard usage today
costguard budget status
```

Validate:
- Cline receives a response
- usage is recorded
- no prompt/response content is logged by default
- budget action is understandable
- provider `429` errors are treated as upstream quota/rate limits, not local budget failures

## Phase 9 - Optional Basic Cache Check

Keep the safe default unless explicitly testing cache:

```text
COSTGUARD_CACHE_MODE=disabled
COSTGUARD_CACHE_STORE_CONTENT=false
```

If asked to validate basic cache, use only safe direct proxy requests, not Cline first:

```powershell
costguard cache enable --mode basic
$env:COSTGUARD_CACHE_STORE_CONTENT = "true"
$env:COSTGUARD_CACHE_MAX_ENTRIES = "1000"
$env:COSTGUARD_CACHE_MAX_SIZE_MB = "100"
$env:COSTGUARD_CACHE_EVICTION_POLICY = "lru"
```

Send the same safe direct request twice. Expected evidence:

```text
cache_misses=1
cache_hits=1
cache_tokens_saved > 0
functional=True
```

Return to the safe default:

```powershell
costguard cache disable
$env:COSTGUARD_CACHE_STORE_CONTENT = "false"
```

Semantic cache is experimental until embeddings, vector storage, similarity thresholds, semantic hit metrics, and tests exist.

## Phase 10 - Optional Headroom Check

Use only when Headroom is intentionally installed:

```powershell
uv sync --extra dev --extra headroom
uv run costguard headroom status
uv tool install --editable ".[headroom]" --link-mode=copy --force
costguard headroom status
costguard headroom test --sample repeated
costguard headroom test --sample long-context
```

`headroom test` is offline and does not call the upstream model. It prints metadata only and does not print sample content.

If the adapter runs but returns `skipped_no_change`, compare input shapes offline before spending more quota:

```powershell
costguard headroom test --sample repeated --input-shape messages-list --force
costguard headroom test --sample repeated --input-shape raw-text --force
costguard headroom test --sample repeated --input-shape openai-payload --force
costguard headroom test --sample repeated --input-shape concatenated-messages-text --force
```

Read `adapter_result_keys`, `normalized_result_shape`, and `payload_reconstruction_status`.

End-to-end Headroom evidence requires real Cline/CostGuard traffic and consumes quota:

```powershell
costguard usage today
```

Evidence:
- `headroom_applied_count > 0`
- `headroom_tokens_saved > 0` when the prompt/context is long enough
- `headroom_reduction_ratio > 0` when compression is effective

If `headroom_applied_count` stays `0`, inspect:

```text
headroom_skipped_count
headroom_last_skip_reason
```

`enabled=True` and `active=True` only prove that Headroom is installed/configured. Until a real request shows `headroom_applied_count > 0`, treat Headroom as experimental for that workstation/upstream path.

`outputs_reduced` is output truncation, not Headroom evidence.

## Phase 11 - Optional Claude Code Validation

Do not configure real Claude Code until I explicitly confirm.

Before real setup, explain:
- Cost Guard supports an Anthropic-compatible `/v1/messages` route with streaming.
- `ANTHROPIC_MODEL=cg-active` enables model switching with `costguard use cheap|standard|strong`.
- Setup, backup, uninstall, headers, aliases, and proxy behavior are covered by tests/mocks.
- Real validation requires a Claude Code license/key and an Anthropic-compatible upstream.
- The official VS Code plugin is validated only when traffic reaches Cost Guard and appears in usage.

First test isolated settings:

```powershell
$env:COSTGUARD_HOME = "$(Get-Location)\.tmp\costguard"
$env:COSTGUARD_CLAUDE_HOME = "$(Get-Location)\.tmp\claude"
costguard setup --tool claude-code --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard doctor
costguard uninstall --yes
```

Then clear temporary variables before real setup:

```powershell
Remove-Item Env:COSTGUARD_HOME -ErrorAction SilentlyContinue
Remove-Item Env:COSTGUARD_CLAUDE_HOME -ErrorAction SilentlyContinue
```

Only if I approve touching real Claude Code settings:

```powershell
costguard setup --tool claude-code --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard doctor
```

Confirm `~/.claude/settings.json` or the approved equivalent contains:

```text
ANTHROPIC_BASE_URL=http://127.0.0.1:4040
ANTHROPIC_AUTH_TOKEN=sk-costguard-local
ANTHROPIC_MODEL=cg-active
```

Start Cost Guard:

```powershell
costguard start
```

Run a minimal Claude Code request from the CLI or VS Code plugin:

```text
Say exactly: OK
```

Then check:

```powershell
costguard usage today
costguard budget status
costguard status
```

Validate:
- Claude Code gets a response
- `usage today` increments
- `top model` is the expected `cg-*` alias
- budget remains clear
- `costguard use cheap|standard|strong` changes routing while `ANTHROPIC_MODEL` stays `cg-active`
- uninstall restores previous settings

## Uninstall

Before uninstalling, explain what will happen.

```powershell
costguard uninstall
```

Do not run purge unless I explicitly ask:

```powershell
costguard uninstall --purge --yes
```

## Final Summary

At the end, report:
- tests run and result
- isolated smoke tests run and result
- whether global `costguard` works
- direct proxy test result
- Cline task result
- Claude Code result, if tested
- pricing refresh result, if configured
- cache/headroom result, if tested
- any `payload blocked by secret filter` or upstream `429` errors
- files/settings touched
- how to start Cost Guard each day
- how to view usage
- how to change budget
- how to edit rules
- how to uninstall
````
