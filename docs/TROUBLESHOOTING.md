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
Model ID: cg-standard
```

Also confirm `OPENAI_UPSTREAM_BASE_URL`, `OPENAI_UPSTREAM_API_KEY`, and model variables are set in `.env`.

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

Run:

```bash
costguard doctor
```

Inspect `~/.claude/settings.json` or your `COSTGUARD_CLAUDE_HOME` equivalent. Confirm:

```text
ANTHROPIC_BASE_URL=http://127.0.0.1:4040
ANTHROPIC_AUTH_TOKEN=sk-costguard-local
ANTHROPIC_MODEL=cg-standard
```

Also confirm `ANTHROPIC_UPSTREAM_BASE_URL`, `ANTHROPIC_UPSTREAM_API_KEY`, and model variables are set in `.env`.

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

## OneDrive Hardlink Failures

Corporate Windows repos often live under OneDrive. Some installers try to create hardlinks and fail with filesystem errors. Use copy mode:

```powershell
uv pip install -e ".[dev]" --python .venv\Scripts\python.exe --link-mode=copy
uv tool install --editable "." --link-mode=copy
```

This avoids hardlink assumptions and keeps the install local to the machine.

## Pricing Catalog

The prices in `settings.yaml` are fallback estimates. For real cost reporting, configure a provider model catalog endpoint in `.env` and refresh local pricing:

```text
COSTGUARD_PRICING_URL=
COSTGUARD_PRICING_API_KEY_ENV=
COSTGUARD_PRICING_API_KEY=
COSTGUARD_PRICING_AUTH_HEADER=x-api-key
COSTGUARD_PRICING_AUTH_SCHEME=
```

```powershell
costguard pricing refresh --help
costguard pricing refresh
costguard pricing status
```

For work-PC validation, prefer `--api-key-env` so keys stay out of shell history:

```powershell
$env:PRICING_API_KEY = "<REDACTED>"
costguard pricing configure --endpoint https://models.example.com/v1/models --api-key-env PRICING_API_KEY --auth-header x-api-key
costguard pricing refresh --dry-run
```

Do not print or commit real pricing API keys. The refresh command stores normalized model prices in `~/.costguard/config/pricing.yaml` and the raw model catalog in `~/.costguard/cache/models.json`.

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
```

## Review Logs

Usage metadata:

```bash
costguard usage today
costguard usage month
```

Raw local logs are under:

```text
~/.costguard/logs/
```

Prompts and responses are not logged by default.
