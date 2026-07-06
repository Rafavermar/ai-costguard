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
Model ID: cg-active
```

Use `cg-active` for dynamic routing. Then `costguard use cheap|standard|strong` changes the upstream model without editing Cline again. Use `cg-standard`, `cg-cheap`, or `cg-strong` only when you want Cline pinned to a fixed category.

## Claude And Anthropic-Compatible Paths

There are three separate scenarios. Keep them distinct.

**A. Cline + Cost Guard + Claude-family models through OpenAI-compatible API**

This is the recommended beta path when your company/provider exposes Claude-family models through an OpenAI-compatible gateway. Keep using Cline settings above and map local categories in `.env`:

```text
OPENAI_UPSTREAM_BASE_URL=
OPENAI_UPSTREAM_API_KEY=
OPENAI_MODEL_CHEAP=<haiku-or-small-model>
OPENAI_MODEL_STANDARD=<sonnet-or-standard-model>
OPENAI_MODEL_STRONG=<opus-or-strong-model>
```

This path is validated with Cline and `cg-active`.

**B. Claude Code + Cost Guard + Anthropic-compatible API**

Cost Guard implements `/v1/messages`, SSE streaming passthrough, Claude Code/Anthropic header forwarding, `ANTHROPIC_UPSTREAM_*`, model mapping, budget/usage, pricing lookup, cache, Headroom path, setup backup, hooks, and uninstall restore. It is covered by mock tests, but real end-to-end validation needs a licensed Claude Code user and an Anthropic-compatible upstream key.

```text
ANTHROPIC_UPSTREAM_BASE_URL=
ANTHROPIC_UPSTREAM_API_KEY=
ANTHROPIC_UPSTREAM_AUTH_HEADER=x-api-key
ANTHROPIC_UPSTREAM_AUTH_SCHEME=
ANTHROPIC_MODEL_CHEAP=
ANTHROPIC_MODEL_STANDARD=
ANTHROPIC_MODEL_STRONG=
```

`setup --tool claude-code` sets Claude Code to use:

```text
ANTHROPIC_BASE_URL=http://127.0.0.1:4040
ANTHROPIC_AUTH_TOKEN=sk-costguard-local
ANTHROPIC_MODEL=cg-active
```

For Claude Code model switching, keep `ANTHROPIC_MODEL=cg-active`. Then `costguard use cheap|standard|strong` changes the routed upstream model without editing Claude Code settings. If Claude Code is pinned to `cg-standard`, `cg-cheap`, or `cg-strong`, it behaves like a fixed category.

Validate only with isolated homes first:

```powershell
$env:COSTGUARD_HOME = "$(Get-Location)\.tmp\costguard"
$env:COSTGUARD_CLAUDE_HOME = "$(Get-Location)\.tmp\claude"
costguard setup --tool claude-code --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard doctor
costguard uninstall --yes
```

Do not touch real `~/.claude/settings.json` unless the user explicitly authorizes it.

**C. Official Claude Code VS Code Plugin**

The expected path is the same local Anthropic-compatible gateway: Claude Code settings point to `http://127.0.0.1:4040` and `ANTHROPIC_MODEL=cg-active`. Treat the plugin as pending smoke validation until a licensed user proves that plugin traffic routes through Cost Guard and usage/budget are recorded.

Before declaring plugin support, validate: setup backup/restore, real `/v1/messages` streaming request, model alias resolution, usage/budget records, pricing resolution, hooks, and uninstall.

## Daily Checks

Inspect install health, proxy state, usage, and local budget.

```bash
costguard status
costguard doctor
costguard usage today
costguard budget status
```

## Usage Metrics

`costguard usage today` is metadata-only by default. It does not store prompts or responses.

Important fields:

```text
outputs_reduced              output limits truncated an oversized upstream response
headroom_applied_count       requests where Headroom transformed the input payload
headroom_input_chars_before  input payload size before Headroom
headroom_input_chars_after   input payload size after Headroom
headroom_input_tokens_before estimated input tokens before Headroom
headroom_input_tokens_after  estimated input tokens after Headroom
headroom_tokens_saved        estimated input tokens saved by Headroom
headroom_reduction_ratio     estimated saved/input ratio, for example 0.35 means 35%
headroom_skipped_count       requests where Headroom was enabled but not applied
headroom_last_skip_reason    latest skip reason, such as skipped_no_change
cache_hits                   requests served from local response cache
cache_misses                 cacheable requests sent upstream and then stored
cache_hit_ratio              hits divided by hits + misses
cache_tokens_saved           estimated tokens not sent upstream because of cache hits
cache_cost_saved             estimated local cost avoided because of cache hits
```

Do not use `outputs_reduced` as cache or Headroom evidence. It belongs to output limits, not request compression or cache hits. `enabled=True` and `active=True` in `headroom status` mean the adapter is installed and configured; real request compression is only proven when `headroom_applied_count > 0`.

## Model Routing With Cline And Claude Code

Cline sends the Model ID configured in its UI on every request. Claude Code sends the model from its settings or UI/session state. If either client is set to `cg-standard`, it keeps asking for `cg-standard` even if Cost Guard active model is `cg-cheap`.

For dynamic switching, configure the client with:

```text
Model ID: cg-active
```

For Claude Code this is:

```text
ANTHROPIC_MODEL=cg-active
```

Then switch the local model category; real model IDs stay in local `.env`.

```bash
costguard use cheap
costguard use standard
costguard use strong
```

Canonical fixed aliases are `cg-cheap`, `cg-standard`, and `cg-strong`. The dynamic alias `cg-active` resolves to whichever fixed alias is currently selected by `costguard use`.

If a client is configured with `cg-standard`, it stays on standard even after `costguard use cheap`. If it is configured with `cg-active`, `costguard use cheap|standard|strong` changes routing without touching the client.

Future option, not enabled by default: `COSTGUARD_FORCE_ACTIVE_MODEL=true` could force all incoming requests to the active model regardless of the client-provided model ID.

## Token Usage Notes

Cline can consume many tokens even for a short prompt because it may resend system instructions, task history, selected workspace context, tool metadata, and previous terminal output.

For clean measurements:

```text
Start New Task
Use a minimal prompt
Avoid Retry after secret-filter errors
Keep `.env`, credentials, logs, and screenshots out of Cline context
Check `costguard usage today`
```

If you see `payload blocked by secret filter`, start a new Cline task and test a minimal prompt first. Do not use Retry as the first diagnostic step.

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
costguard pricing configure --endpoint <pricing-catalog-url> --api-key-env PRICING_API_KEY --auth-header x-api-key
```

Validate and cache prices locally.

```bash
costguard pricing status
costguard pricing refresh --dry-run
costguard pricing refresh
```

Do not use the inference endpoint as the pricing source; pricing refresh calls a catalog endpoint and does not consume LLM tokens. The OpenAI-compatible chat/messages endpoint is not a pricing source.

Pricing refresh stores normalized prices in `config/pricing.yaml` and the raw model catalog in `cache/models.json`; it must not store API keys in either file.

## Cache

Manage optional local cache state. Pricing cache is separate from response cache.

```bash
costguard cache status
costguard cache enable --mode basic
costguard cache disable
costguard cache clear
costguard cache clear --responses
costguard cache clear --responses-only
costguard cache clear --pricing
costguard cache clear --pricing-only
costguard cache clear --vectors
costguard cache clear --vectors-only
costguard cache clear --expired
costguard cache inspect
```

Cache modes:

```text
disabled  no response cache
basic     exact-match response cache; requires COSTGUARD_CACHE_STORE_CONTENT=true
semantic  scaffolded/experimental; embeddings are not active yet
```

Recommended beta/default state:

```text
COSTGUARD_CACHE_MODE=disabled
COSTGUARD_CACHE_STORE_CONTENT=false
```

Controlled basic-cache test state:

```text
COSTGUARD_CACHE_STORE_CONTENT=true
COSTGUARD_CACHE_TTL_SECONDS=86400
COSTGUARD_CACHE_MAX_ENTRIES=1000
COSTGUARD_CACHE_MAX_SIZE_MB=100
COSTGUARD_CACHE_EVICTION_POLICY=lru
```

Basic cache is intentionally opt-in because it stores prompt/response content locally under `cache/responses`. Do not enable content storage with prompts that may contain secrets, client data, credentials, tokens, `.env` content, or anything that should not persist locally.

The response cache does not store API keys or headers, skips streaming/tool/multimodal/secret-like requests, only stores successful 2xx responses, expires entries by TTL, and evicts old entries by `COSTGUARD_CACHE_EVICTION_POLICY` when `COSTGUARD_CACHE_MAX_ENTRIES` or `COSTGUARD_CACHE_MAX_SIZE_MB` is exceeded.

`costguard cache clear` clears response/vector runtime cache and preserves `cache/models.json`. Use `--pricing` or `--pricing-only` only when you intentionally want to delete the pricing catalog cache.

Validate basic cache with two identical direct proxy requests, not Cline first. Cline can add history, tool metadata, context, or small internal differences, so two prompts that look identical may not produce the same cache key.

```bash
costguard usage today
```

Expected evidence is `cache_misses=1`, `cache_hits=1`, and positive `cache_tokens_saved` for the repeated request.

`costguard cache status` fields:

```text
mode                  disabled, basic, or semantic
path                  response cache folder, or vector folder in semantic mode
store_content         False means metadata-only; True allows response replay
functional            True only when the current mode/config can return cached responses
ttl_seconds           response cache entry lifetime
max_entries           response cache entry limit
max_size_mb/bytes     response cache disk limit
eviction_policy       lru or fifo
expired_entries       expired entries removed during status/write/clear
evicted_entries       entries removed because limits were exceeded
entries               current mode entry count
response_entries      cached response count
pricing_cache         whether cache/models.json exists
vector_entries        semantic/vector cache file count
size_bytes            approximate cache disk size
note                  metadata-only, semantic experimental, or n/a
```

To return to the safe default:

```bash
costguard cache disable
# then set locally:
COSTGUARD_CACHE_STORE_CONTENT=false
```

## Headroom

Optional request compression requires a compatible external package.

```bash
costguard headroom status
costguard headroom enable
costguard headroom disable
```

Install only when needed:

```powershell
uv sync --extra dev --extra headroom
uv run costguard headroom status
```

That validates Headroom inside the repo environment with `uv run`.

If the global `costguard` command should also have Headroom available:

```powershell
uv tool install --editable ".[headroom]" --link-mode=copy --force
costguard headroom status
```

`enabled=False` is expected when `COSTGUARD_HEADROOM_ENABLED=false`. End-to-end Headroom compression needs a real Cline/CostGuard request and therefore consumes LLM quota; run it only when quota is available.

Headroom status fields:

```text
available=True   package/module can be imported
compatible=True  Cost Guard found a supported adapter function
enabled=False    expected when COSTGUARD_HEADROOM_ENABLED=false
active=False     expected when disabled or when no request is being transformed
```

To validate Headroom end-to-end:

```powershell
costguard headroom status
costguard headroom test --sample repeated
costguard start
# Send a safe, non-secret, sufficiently long prompt from a new Cline task.
costguard usage today
```

Use offline samples before spending tokens:

```powershell
costguard headroom test --sample short
costguard headroom test --sample repeated
costguard headroom test --sample long-context
```

The command prints only metadata: adapter, input shape, message count, before/after chars, estimated tokens, `changed`, `skip_reason`, and result type. It does not print sample content or call the upstream model.

If Headroom is installed but disabled and you only want an offline adapter check:

```powershell
costguard headroom test --sample repeated --force
```

Offline evidence is `changed=True`, positive `tokens_saved`, and positive `reduction_ratio`. Real traffic evidence is `headroom_applied_count > 0`; compression evidence is `headroom_tokens_saved > 0` or a positive `headroom_reduction_ratio`. Small prompts may apply Headroom without saving much.

If `headroom_applied_count` remains `0`, inspect:

```text
headroom_skipped_count
headroom_last_skip_reason
```

Known skip reasons:

```text
skipped_disabled      Headroom is disabled in local config
skipped_not_eligible  request/client shape is not eligible
skipped_streaming     streaming request skipped for safe passthrough
skipped_tools         tools/functions request skipped to avoid tool-call changes
skipped_no_messages   payload has no messages list
skipped_adapter_error adapter failed or returned an invalid shape
skipped_no_change     adapter ran but returned the same payload
```

Until a real request shows `headroom_applied_count > 0`, treat Headroom as installed/configured but still experimental for that workstation/upstream path.

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
docs/prompts/work-pc-validation-prompt.md
docs/WORK_PC_UPDATE.md
docs/TROUBLESHOOTING.md
```
