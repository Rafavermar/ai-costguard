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
