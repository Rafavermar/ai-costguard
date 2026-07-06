# Update ai-costguard On A Corporate PC

Use this when a corporate laptop has a local checkout of a company fork and you need to update the local CLI without touching client repos or consuming LLM tokens.

## Flow

```text
Original repo updated
  -> Sync company fork in GitHub
  -> Pull local work-PC checkout
  -> Stop CostGuard
  -> Recreate .venv with uv
  -> Refresh global costguard command
  -> Run offline validations
```

Short version:

```powershell
git fetch origin --prune
git pull --ff-only origin main
costguard stop
Get-Process python,uv,costguard -ErrorAction SilentlyContinue | Select-Object Name,Id,Path
Remove-Item -Recurse -Force .\.venv
uv sync --extra dev
uv tool install --editable "." --link-mode=copy --force
costguard --help
uv run pytest
costguard doctor
costguard pricing status
costguard headroom status
costguard cline-config
```

Use `uv sync --extra dev --extra headroom` and `uv tool install --editable ".[headroom]" --link-mode=copy --force` only when validating Headroom.

## Rules

- Run this inside the `ai-costguard` repo, not inside a client repo.
- Keep `origin` pointing to the company fork.
- Use `uv`, not direct `pip`, for this update flow.
- Do not print or commit secrets, company endpoints, logs, or screenshots with sensitive data.
- Do not test Cline against the model during offline validation.

## 1. Sync The Company Fork

Do this in GitHub web.

```text
Open company fork -> Sync fork -> Update branch
```

This avoids requiring an `upstream` remote on the work PC.

## 2. Pull The Local Checkout

Open PowerShell in the local `ai-costguard` checkout.

```powershell
Set-Location "PATH_TO_REPO\ai-costguard"

git remote -v
git status
git branch --show-current
git fetch origin --prune
git pull --ff-only origin main
git log --oneline -10
```

Expected: branch is `main`, `origin` is the company fork, and pull completes without a merge.

If local changes block the pull, do not run `git reset --hard` until you know what would be lost.

## 3. Stop CostGuard

Stop the proxy before recreating `.venv`.

```powershell
costguard stop
Get-Process python,uv,costguard -ErrorAction SilentlyContinue | Select-Object Name,Id,Path,StartTime
```

Only close processes whose `Path` belongs to this repo or to CostGuard.

## 4. Recreate The uv Environment

Recreate `.venv` to avoid stale packages, `missing RECORD file`, and Windows file-lock issues.

```powershell
Remove-Item -Recurse -Force .\.venv
uv sync --extra dev
```

Expected: `.venv` is created and `ai-costguard` is installed from the local repo path.

If validating Headroom in the repo environment:

```powershell
uv sync --extra dev --extra headroom
uv run costguard headroom status
```

## 5. Refresh The Global CLI

Run this after every repo update if teammates use `costguard` as a global command.

```powershell
uv tool install --editable "." --link-mode=copy --force
costguard --help
```

This is the standard CLI update command, not a Headroom-specific command.

If the global command must include Headroom:

```powershell
uv tool install --editable ".[headroom]" --link-mode=copy --force
costguard headroom status
```

Fallback when `--force` is unsupported:

```powershell
uv tool uninstall costguard
uv tool install --editable "." --link-mode=copy
costguard --help
```

If you do not use a global command, use `uv run costguard ...` from inside the repo.

## 6. Validate Offline

Run checks that do not call an LLM.

```powershell
uv run pytest
costguard --help
costguard doctor
costguard pricing status
costguard headroom status
costguard cline-config
uv run costguard rules test "cat .env"
uv run costguard rules test "git diff"
uv run costguard rules test "find ."
uv run costguard cache status
```

Expected: tests pass, `.env` is blocked, noisy commands are rewritten, and status commands return local state.

`basic` cache becomes functional only when `COSTGUARD_CACHE_STORE_CONTENT=true` is set locally. Keep content storage disabled during offline update validation unless you are explicitly testing response cache behavior.

## 7. Optional Pricing Catalog

Configure only if the company/provider exposes a pricing catalog endpoint.

```text
# Inference endpoint: used by Cline/Claude Code to call the model.
OPENAI_UPSTREAM_BASE_URL=
OPENAI_UPSTREAM_API_KEY=

# Pricing catalog endpoint: used only by costguard pricing refresh.
COSTGUARD_PRICING_URL=
COSTGUARD_PRICING_API_KEY_ENV=
COSTGUARD_PRICING_API_KEY=
COSTGUARD_PRICING_AUTH_HEADER=x-api-key
COSTGUARD_PRICING_AUTH_SCHEME=
```

If the same key works for both endpoints:

```text
COSTGUARD_PRICING_API_KEY_ENV=OPENAI_UPSTREAM_API_KEY
```

If pricing has a separate key:

```powershell
$env:PRICING_API_KEY = "<REDACTED>"
uv run costguard pricing configure --endpoint <pricing-catalog-url> --api-key-env PRICING_API_KEY --auth-header x-api-key
```

Validate without writing, then refresh local cache.

```powershell
uv run costguard pricing refresh --dry-run
uv run costguard pricing refresh
uv run costguard pricing status
```

Do not use the inference endpoint as `COSTGUARD_PRICING_URL`; the OpenAI-compatible chat/messages endpoint is not a pricing source. Pricing refresh must not store API keys in `config/pricing.yaml` or `cache/models.json`.

## 8. Optional Headroom Check

Run only when validating request compression.

```powershell
uv sync --extra dev --extra headroom
uv run costguard headroom status
```

This validates Headroom in the repo environment with `uv run`.

If the global `costguard` command should also have Headroom available:

```powershell
uv tool install --editable ".[headroom]" --link-mode=copy --force
costguard headroom status
```

The standard global CLI update remains:

```powershell
uv tool install --editable "." --link-mode=copy --force
```

`enabled=False` is expected when `COSTGUARD_HEADROOM_ENABLED=false`. A real end-to-end Headroom compression test requires Cline/CostGuard traffic and consumes LLM quota, so run it only when quota is available.

End-to-end evidence after a safe Cline request:

```powershell
costguard usage today
```

Expected evidence:

```text
headroom_applied_count > 0
headroom_tokens_saved > 0
headroom_reduction_ratio > 0
```

`outputs_reduced` is not Headroom evidence; it means output limits truncated an oversized response.

## 9. Optional Basic Cache Check

Run only when validating repeated-request behavior. This stores prompt/response content locally, so use safe test prompts and never include secrets, client data, credentials, `.env` content, or sensitive business context.

```powershell
uv run costguard cache enable --mode basic
$env:COSTGUARD_CACHE_STORE_CONTENT = "true"
$env:COSTGUARD_CACHE_MAX_ENTRIES = "1000"
$env:COSTGUARD_CACHE_MAX_SIZE_MB = "100"
$env:COSTGUARD_CACHE_EVICTION_POLICY = "lru"
```

Send the same safe direct proxy request twice, not a Cline prompt first. Cline can add task history, tool metadata, context, or tiny request differences that change the cache key.

```powershell
costguard usage today
costguard cache status
```

Expected evidence:

```text
cache_misses=1
cache_hits=1
cache_tokens_saved > 0
```

If the first direct request is a miss and the second identical direct request is a hit, basic response cache is validated. After that, you can try Cline, but do not assume it will hit for visually similar prompts.

Return to the safe default:

```powershell
uv run costguard cache disable
$env:COSTGUARD_CACHE_STORE_CONTENT = "false"
```

Semantic cache is not a production embeddings cache yet; keep it disabled unless you are working on embeddings/vector retrieval, similarity thresholds, semantic hit metrics, and tests.

## 10. Optional Isolated Setup Smoke

Use repo-local temp paths to avoid touching real home config.

```powershell
$env:COSTGUARD_HOME = "$(Get-Location)\.tmp\costguard"
$env:COSTGUARD_CLAUDE_HOME = "$(Get-Location)\.tmp\claude"

uv run costguard setup --tool cline --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
uv run costguard doctor
uv run costguard status
uv run costguard cline-config
uv run costguard uninstall --yes
```

With `--tool cline`, setup prints Cline config and does not edit Claude Code settings.

For Cline model routing, use `Model ID: cg-active` when you want `costguard use cheap|standard|strong` to switch the active category. Use `cg-standard`, `cg-cheap`, or `cg-strong` only when you want a fixed category.

## Troubleshooting

`costguard stop` returns Access denied:

```powershell
Get-Process -Id <PID> -ErrorAction SilentlyContinue | Select-Object Name,Id,Path,StartTime
Get-Process python,uv,costguard -ErrorAction SilentlyContinue | Select-Object Name,Id,Path,StartTime
Get-NetTCPConnection -LocalPort 4040 -ErrorAction SilentlyContinue
```

If no process exists and nothing is listening on the port, it is probably a stale PID or an already-finished process. Do not kill processes blindly.

`uv sync` access denied, `.venv` inconsistent, or `missing RECORD file`:

```powershell
costguard stop
Get-Process python,uv,costguard -ErrorAction SilentlyContinue | Select-Object Name,Id,Path,StartTime
Remove-Item -Recurse -Force .\.venv
uv sync --extra dev
```

Use `uv sync --extra dev --extra headroom` instead when validating Headroom.

`pip` missing in `.venv`:

```powershell
uv run costguard --help
uv run pytest
```

This is expected in uv-managed environments. Do not switch the normal work-PC flow to direct `pip`.

`uv.lock` appears as untracked after `uv sync`:

```powershell
git status
Remove-Item .\uv.lock
git status
```

Do not create local commits on the work PC just to add `uv.lock`. If the project decides to version it later, do that in the original repo.

`429 true` from Cline: upstream provider quota/rate limit; validate offline and wait or change tier/credentials.

`payload blocked by secret filter`: start a new Cline task; avoid retrying the same accumulated context.

## Final Checklist

- [ ] Company fork synced in GitHub.
- [ ] Local checkout pulled with `git pull --ff-only origin main`.
- [ ] Working tree clean.
- [ ] CostGuard stopped before `.venv` recreation.
- [ ] No relevant `python`, `uv`, or `costguard` process is locking the repo.
- [ ] `.venv` recreated with `uv sync --extra dev`.
- [ ] Global CLI refreshed with `uv tool install --editable "." --link-mode=copy --force`, if used.
- [ ] If Headroom applies, global CLI installed with `uv tool install --editable ".[headroom]" --link-mode=copy --force`.
- [ ] `uv run pytest` passes.
- [ ] `costguard doctor` OK.
- [ ] `costguard pricing status` checked.
- [ ] `costguard pricing refresh --dry-run` OK when pricing is configured.
- [ ] `costguard pricing refresh` OK when pricing is configured.
- [ ] Cline configured with `Model ID: cg-active`.
- [ ] `costguard use cheap|standard|strong` tested if model switching matters.
- [ ] Offline validations passed.
- [ ] No client repos touched.
- [ ] No LLM tokens consumed during validation.
- [ ] No secrets or company endpoints printed or committed.
- [ ] No local work-PC commits created accidentally.
