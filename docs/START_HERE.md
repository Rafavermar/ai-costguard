# Start Here

Use this page first. It tells humans and coding agents which flow to run without reading every document.

## Choose The Flow

| Situation | Use |
| --- | --- |
| First controlled validation on a work PC | `docs/prompts/work-pc-validation-prompt.md` |
| Install or operate Cost Guard manually | `docs/RUNBOOK.md` |
| Update an existing corporate checkout | `docs/WORK_PC_UPDATE.md` |
| Debug a failure | `docs/TROUBLESHOOTING.md` |
| Understand architecture or security | `docs/ARCHITECTURE.md`, `docs/SECURITY.md` |

## Rules For Agents

- Do not touch client repos unless explicitly asked.
- Do not print real `.env` values, API keys, company endpoints, screenshots, or logs with secrets.
- Use isolated paths for smoke tests unless the user explicitly wants real setup.
- Do not call Cline or the model during offline validation.
- Prefer `uv` and `--link-mode=copy` on Windows/OneDrive work laptops.

## First Work-PC Validation

Use the reusable prompt with Cline or another coding agent.

```text
docs/prompts/work-pc-validation-prompt.md
```

The prompt covers Python/uv detection, isolated smoke, global `costguard` install, real Cline setup, pricing catalog config, and final validation.

## Manual Install

Run inside the `ai-costguard` repo.

```powershell
uv venv .venv --python 3.14
uv pip install -e ".[dev]" --python .venv\Scripts\python.exe --link-mode=copy
uv tool install --editable "." --link-mode=copy
costguard --help
```

Use any installed Python `>=3.10`; keep copy mode under OneDrive.

## Safe Smoke

Use repo-local temp paths before touching real workstation settings.

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

## Real `.env`

Edit only local `.env`; never commit real values.

```text
OPENAI_UPSTREAM_BASE_URL=
OPENAI_UPSTREAM_API_KEY=
OPENAI_MODEL_CHEAP=
OPENAI_MODEL_STANDARD=
OPENAI_MODEL_STRONG=

# Optional Anthropic-compatible upstream for Claude Code validation.
ANTHROPIC_UPSTREAM_BASE_URL=
ANTHROPIC_UPSTREAM_API_KEY=
ANTHROPIC_UPSTREAM_AUTH_HEADER=x-api-key
ANTHROPIC_UPSTREAM_AUTH_SCHEME=
ANTHROPIC_MODEL_CHEAP=
ANTHROPIC_MODEL_STANDARD=
ANTHROPIC_MODEL_STRONG=

COSTGUARD_PRICING_URL=
COSTGUARD_PRICING_API_KEY_ENV=OPENAI_UPSTREAM_API_KEY
COSTGUARD_PRICING_API_KEY=
COSTGUARD_PRICING_AUTH_HEADER=x-api-key
COSTGUARD_PRICING_AUTH_SCHEME=

# Safe default for response cache.
COSTGUARD_CACHE_MODE=disabled
COSTGUARD_CACHE_STORE_CONTENT=false
COSTGUARD_CACHE_MAX_ENTRIES=1000
COSTGUARD_CACHE_MAX_SIZE_MB=100
COSTGUARD_CACHE_EVICTION_POLICY=lru
```

`OPENAI_UPSTREAM_BASE_URL` calls models. `COSTGUARD_PRICING_URL` fetches model prices. They are different endpoints; they may share the same key if your company allows it.

For beta use, prefer Cline + Cost Guard first because it is work-PC validated. Claude Code via `ANTHROPIC_UPSTREAM_*` is gateway-ready with `/v1/messages` streaming and `cg-active`, but still needs real validation with a licensed user/key. The official Claude Code VS Code plugin should be treated as pending smoke validation until custom endpoint/proxy behavior is proven.

## Update Existing CLI

Run this after the company fork has been synced.

```powershell
git fetch origin --prune
git pull --ff-only origin main
costguard stop
Remove-Item -Recurse -Force .\.venv
uv sync --extra dev
uv tool install --editable "." --link-mode=copy --force
uv run pytest
uv run costguard rules test "cat .env"
uv run costguard pricing status
```

Full procedure: `docs/WORK_PC_UPDATE.md`.

Use this instead if the global `costguard` command must include Headroom:

```powershell
uv tool install --editable ".[headroom]" --link-mode=copy --force
costguard headroom status
```

## Recommended Cline Configuration

Start the proxy, then paste the printed config into Cline.

```powershell
costguard start
costguard cline-config
```

Expected Cline values:

```text
Provider: OpenAI Compatible
Base URL: http://127.0.0.1:4040/v1
API Key: sk-costguard-local
Model ID: cg-active
```

`cg-active` follows `costguard use cheap|standard|strong`. Use `cg-standard`, `cg-cheap`, or `cg-strong` only for fixed routing.

Validate switching:

```powershell
costguard use cheap
costguard status
costguard cline-config
```

## Clean Token Measurements

Cline may resend task history, system prompt, tool metadata, selected files, and workspace context. For clean usage checks, start a new task, use a minimal prompt, avoid Retry after secret-filter errors, and then run:

```powershell
costguard usage today
```

For Headroom validation, first run `costguard headroom test --sample repeated` offline. Then, for real traffic, look for `headroom_applied_count`, `headroom_tokens_saved`, and `headroom_reduction_ratio`. If applied count is `0`, check `headroom_skipped_count` and `headroom_last_skip_reason`. `outputs_reduced` means output truncation, not Headroom compression.

For basic cache validation, do not start with Cline. Enable `basic`, set `COSTGUARD_CACHE_STORE_CONTENT=true` only for safe test prompts, send two identical direct proxy requests, and expect `cache_misses=1`, `cache_hits=1`. Return to the safe default with `costguard cache disable` and `COSTGUARD_CACHE_STORE_CONTENT=false`.

## Common Errors

| Symptom | First action |
| --- | --- |
| `payload blocked by secret filter` | Start a new Cline task; do not retry old context. |
| `[OPENAI] 429 true` | Treat as upstream quota/rate limit, not local budget. |
| `uv sync` access denied | Stop CostGuard and check `python`, `uv`, `costguard` processes. |
| `costguard` not found | Run `uv tool install --editable "." --link-mode=copy --force`. |
| Pricing refresh fails | Confirm `COSTGUARD_PRICING_URL` is a catalog endpoint, not inference endpoint. |

Full fixes: `docs/TROUBLESHOOTING.md`.
