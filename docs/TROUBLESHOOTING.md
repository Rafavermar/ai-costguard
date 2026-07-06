# Troubleshooting

## Cost Guard Does Not Start

Run:

```bash
costguard doctor
costguard status
```

Check that `~/.costguard/.env` exists and that upstream variables are set.

## Port Occupied

Use another port:

```bash
costguard start --port 4041
```

Then update Cline Base URL and Claude Code settings to match.

## Cline Does Not Connect

Run:

```bash
costguard cline-config
```

Confirm Cline has:

```text
Provider: OpenAI Compatible
Base URL: http://127.0.0.1:4040/v1
API Key: sk-costguard-local
Model ID: cg-active
```

Use `cg-active` if you expect `costguard use cheap|standard|strong` to change routing. If Cline is set to `cg-standard`, it is pinned to that fixed category. Also confirm `OPENAI_UPSTREAM_BASE_URL`, `OPENAI_UPSTREAM_API_KEY`, and model variables are set in `.env`.

## Cline Payload Blocked By Secret Filter

If Cline shows an error like:

```text
payload blocked by secret filter
```

do not assume the latest user message is the problem. Cline may be resending accumulated task context that contains credentials, `.env` content, terminal output, or previous discussion of secrets.

Recommended check:

1. Start a new Cline task.
2. Do not use Retry on the old task.
3. Send a minimal prompt such as `Di OK`.
4. Check `costguard usage today`.

If the new task works, document the likely cause as accumulated Cline context blocked by the corporate secret filter. Avoid adding `.env`, `.env.*`, `databricks.yml`, key files, token files, `.cline`, `.vscode`, or credential screenshots as Cline context.

## Upstream 429 Is Not Local Budget

If Cline or the proxy returns an upstream error like:

```text
[OPENAI] 429 true
```

and `costguard budget status` still shows `mode=warn` and `action=allow`, the request was allowed by Cost Guard and rejected by the upstream provider quota/rate limit. Cost Guard budget controls local spend policy; it does not increase corporate provider quotas.

## Claude Code Does Not Connect

This section refers to Claude Code configured through `~/.claude/settings.json` or the equivalent `COSTGUARD_CLAUDE_HOME`. The VS Code plugin should use the same local gateway only after a licensed-user smoke proves that traffic reaches Cost Guard.

Run:

```bash
costguard doctor
```

Inspect `~/.claude/settings.json` or your `COSTGUARD_CLAUDE_HOME` equivalent. Confirm:

```text
ANTHROPIC_BASE_URL=http://127.0.0.1:4040
ANTHROPIC_AUTH_TOKEN=sk-costguard-local
ANTHROPIC_MODEL=cg-active
```

Also confirm `ANTHROPIC_UPSTREAM_BASE_URL`, `ANTHROPIC_UPSTREAM_API_KEY`, optional `ANTHROPIC_UPSTREAM_AUTH_HEADER` / `ANTHROPIC_UPSTREAM_AUTH_SCHEME`, and model variables are set in `.env`.

If model switching does not appear to work, confirm Claude Code is not pinned to `cg-standard`, `cg-cheap`, or `cg-strong`. Dynamic switching requires `ANTHROPIC_MODEL=cg-active`.

If your company exposes Claude-family models through an OpenAI-compatible gateway, the simpler beta path is to use Cline with `OPENAI_MODEL_CHEAP/STANDARD/STRONG` mapped to those models and `Model ID: cg-active`.

## Missing Variables

Edit:

```bash
~/.costguard/.env
```

In isolated development, edit:

```bash
.tmp/costguard/.env
```

## Windows Command Notes

If `python` is not in PATH, use the launcher approved on that machine, such as `py`, `uv`, or the corporate Python path. Do not change the global Python install without checking first.

If `uv` is available, install dependencies and the global `costguard` command with copy mode:

```powershell
uv pip install -e ".[dev]" --python .venv\Scripts\python.exe --link-mode=copy
uv tool install --editable "." --link-mode=copy
costguard --help
```

If `costguard` is not in PATH after editable install, either install it as a tool with `uv tool install --editable "." --link-mode=copy` or call the virtualenv executable directly:

```powershell
.\.venv\Scripts\costguard.exe doctor
.\.venv\Scripts\costguard.exe status
```

PowerShell does not always behave like Bash for command chaining. If `&&` fails, run commands separately or use `;`.

## `costguard stop` Access Denied

Check whether the process still exists and whether the proxy port is actually listening:

```powershell
Get-Process -Id <PID> -ErrorAction SilentlyContinue | Select-Object Name,Id,Path,StartTime
Get-Process python,uv,costguard -ErrorAction SilentlyContinue | Select-Object Name,Id,Path,StartTime
Get-NetTCPConnection -LocalPort 4040 -ErrorAction SilentlyContinue
```

If no process exists and the port is not listening, treat it as a stale PID or already-finished process. Do not kill unrelated Python processes blindly.

## OneDrive Hardlink Failures

Corporate Windows repos often live under OneDrive. Some installers try to create hardlinks and fail with filesystem errors. Use copy mode:

```powershell
uv pip install -e ".[dev]" --python .venv\Scripts\python.exe --link-mode=copy
uv tool install --editable "." --link-mode=copy
```

This avoids hardlink assumptions and keeps the install local to the machine.

## `.venv` Missing RECORD Or Access Denied

Stop Cost Guard, check for live processes, and recreate the environment with uv:

```powershell
costguard stop
Get-Process python,uv,costguard -ErrorAction SilentlyContinue | Select-Object Name,Id,Path,StartTime
Remove-Item -Recurse -Force .\.venv
uv sync --extra dev
```

Use `uv sync --extra dev --extra headroom` when validating Headroom.

## `uv.lock` Appears Untracked

For the corporate work-PC update flow, do not create local commits just to add `uv.lock`.

```powershell
git status
Remove-Item .\uv.lock
git status
```

If the project later decides to version `uv.lock`, do that from the original repo workflow.

## Pricing Catalog

The prices in `settings.yaml` are fallback estimates. For real cost reporting, configure a provider model catalog endpoint in `.env` and refresh local pricing. This pricing catalog endpoint is separate from the model inference endpoint used for chat/completions or messages:

```text
OPENAI_UPSTREAM_BASE_URL=
OPENAI_UPSTREAM_API_KEY=

COSTGUARD_PRICING_URL=
COSTGUARD_PRICING_API_KEY_ENV=
COSTGUARD_PRICING_API_KEY=
COSTGUARD_PRICING_AUTH_HEADER=x-api-key
COSTGUARD_PRICING_AUTH_SCHEME=
```

If the same company API key works for both endpoints, set `COSTGUARD_PRICING_API_KEY_ENV=OPENAI_UPSTREAM_API_KEY` or `COSTGUARD_PRICING_API_KEY_ENV=ANTHROPIC_UPSTREAM_API_KEY`. If pricing has its own key, point it to a separate shell or local `.env` variable such as `PRICING_API_KEY`.

```powershell
costguard pricing refresh --help
costguard pricing refresh
costguard pricing status
```

For work-PC validation, prefer `--api-key-env` so keys stay out of shell history:

```powershell
$env:PRICING_API_KEY = "<REDACTED>"
costguard pricing configure --endpoint <pricing-catalog-url> --api-key-env PRICING_API_KEY --auth-header x-api-key
costguard pricing refresh --dry-run
```

Do not print or commit real pricing API keys. The refresh command stores normalized model prices in `~/.costguard/config/pricing.yaml` and the raw model catalog in `~/.costguard/cache/models.json`.
Those files must not contain API keys.

## Claude Code Settings Look Wrong

Find backups:

```bash
ls ~/.claude/settings.json.bak.costguard-*
```

Restore manually by copying the newest backup over `settings.json`, or run:

```bash
costguard uninstall
```

## Uninstall

```bash
costguard uninstall
```

This keeps `~/.costguard`.

To delete it:

```bash
costguard uninstall --purge --yes
```

## Clean Cache

```bash
costguard cache clear
costguard cache clear --responses
costguard cache clear --responses-only
costguard cache clear --pricing
costguard cache clear --pricing-only
costguard cache clear --vectors
costguard cache clear --vectors-only
costguard cache clear --expired
```

Default clear removes response/vector runtime cache and preserves the pricing catalog. Use `--pricing` or `--pricing-only` only when you want to remove `cache/models.json`.

If basic cache shows no hits:

```bash
costguard cache status
```

Check:

```text
mode=basic
store_content=True
functional=True
```

If `store_content=False`, basic cache is metadata-only and will not return cached responses. If testing through Cline, validate first with two identical direct proxy requests because Cline can add context, history, or tool metadata that changes the cache key.

If cache grows too much, lower the local limits:

```text
COSTGUARD_CACHE_MAX_ENTRIES=1000
COSTGUARD_CACHE_MAX_SIZE_MB=100
COSTGUARD_CACHE_EVICTION_POLICY=lru
```

## Review Logs

Usage metadata:

```bash
costguard usage today
costguard usage month
```

`outputs_reduced` means output limits truncated a large upstream response. For Headroom evidence, check `headroom_applied_count`, `headroom_tokens_saved`, and `headroom_reduction_ratio`.

If `headroom status` shows `enabled=True` and `active=True` but `headroom_applied_count=0`, Headroom is installed/configured but did not transform that request. Check:

```text
headroom_skipped_count
headroom_last_skip_reason
```

Common reasons are `skipped_streaming`, `skipped_tools`, `skipped_no_messages`, `skipped_adapter_error`, and `skipped_no_change`.

Before spending more LLM quota, run:

```powershell
costguard headroom test --sample repeated
costguard headroom test --sample long-context
```

If the offline test also returns `changed=False` and `skip_reason=skipped_no_change`, the adapter was called but did not compress that sample. Check the adapter contract without calling an upstream model:

```powershell
costguard headroom test --sample repeated --input-shape messages-list --force
costguard headroom test --sample repeated --input-shape raw-text --force
costguard headroom test --sample repeated --input-shape openai-payload --force
costguard headroom test --sample repeated --input-shape concatenated-messages-text --force
```

Read `adapter_result_keys`, `normalized_result_shape`, and `payload_reconstruction_status`. Treat Headroom as installed but not compression-validated until `tokens_saved > 0` offline or `headroom_tokens_saved > 0` in real traffic.

Observed interpretation with the official `headroom.compress` adapter:

```text
messages-list + CompressResult + messages_reconstructed + skipped_no_change
  Headroom was invoked correctly but returned the same messages.

raw-text/openai-payload/concatenated-messages-text + skipped_adapter_error
  The diagnostic shape is incompatible with the official compress(messages) API.
```

Headroom defaults are conservative for coding agents:

```text
compress_user_messages=False
protect_recent=4
min_tokens_to_compress=250
```

A single recent `user` message is therefore expected to produce no reduction. Try realistic tool/log samples first:

```powershell
costguard headroom test --sample tool-output --force
costguard headroom test --sample logs --force
costguard headroom test --sample test-failure --force
costguard headroom test --sample cline-terminal-output --force
costguard headroom test --sample cline-test-output --force
```

For document/RAG-style diagnostics only:

```powershell
costguard headroom test --sample long-context --force --compress-user-messages --protect-recent 0
```

Do not enable `COSTGUARD_HEADROOM_COMPRESS_USER_MESSAGES=true` for real coding traffic unless the user accepts that Headroom may rewrite user-provided context.

If offline samples compress but real Cline traffic still does not, replay a saved local request body:

```powershell
costguard headroom test --from-json payload.json --force
```

Look at:

```text
headroom_candidate_message_count
headroom_compressible_message_count
headroom_protected_message_count
headroom_roles_seen
headroom_roles_compressed
headroom_transforms_applied
```

If `candidate=0`, the real payload does not look like log/tool/test output. If `candidate>0` and `compressible=0`, check whether recent-turn or user-message protection is expected.

Raw local logs are under:

```text
~/.costguard/logs/
```

Prompts and responses are not logged by default.
