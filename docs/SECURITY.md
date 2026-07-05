# Security

AI Cost Guard is intentionally local-first.

## No Content Logging By Default

Usage records store metadata only:

- timestamp
- client
- model alias
- upstream
- estimated input and output chars
- estimated tokens
- estimated cost
- budget action
- rule or security event

Prompts and responses are not stored by default.

## Keys Stay Local

API keys live in `~/.costguard/.env` or in the path selected by `COSTGUARD_HOME`. `.env` is ignored by Git.

Pricing catalog endpoints and API keys are local workstation configuration. Do not commit company-specific `COSTGUARD_PRICING_URL` values, real API keys, or screenshots/logs that reveal them. Prefer `COSTGUARD_PRICING_API_KEY_ENV` or `--api-key-env` so keys stay in environment variables.

## Localhost Proxy

The proxy binds to `127.0.0.1` by default. If another host is selected, Cost Guard prints a warning.

## Claude Code Backups

Before modifying Claude Code settings, Cost Guard writes a backup next to `settings.json`:

```text
settings.json.bak.costguard-YYYYMMDDHHMMSS
```

Uninstall restores from the latest clean backup when available, ignores backups that already contain Cost Guard fragments, and removes Cost Guard backup files after successful cleanup. A localhost `ANTHROPIC_BASE_URL` alone is not treated as Cost Guard; existing user config still gets backed up before setup changes it.

## Reversible Uninstall

`costguard uninstall` restores Claude Code settings from backup or removes only Cost Guard fragments. It keeps Cost Guard home by default. `--purge --yes` is required to delete the local Cost Guard home.

## Secret Blocking

Default rules block:

- `.env`
- private keys
- Terraform state and vars
- secret-like, password-like, credential-like, and token-like paths
- commands such as `env`, `printenv`, and `cat .env`

The proxy also blocks payloads that look like private keys or API key assignments when the secret filter is enabled.

## Cache Risks

Cache is disabled by default. Even when enabled, the MVP stores hashes, metadata, and safe summaries rather than full prompts or responses. Treat any cache as sensitive local developer data.

## Headroom Risks

Headroom can transform request payloads before they reach the upstream model. It is disabled by default and requires the optional `headroom-ai` package or a compatible local adapter. Review Headroom's data handling, model downloads, local cache behavior, and corporate TLS requirements before enabling it in a work environment.

## Do Not Commit Secrets

Never commit:

- `.env`
- `~/.costguard`
- `.claude/settings.local.json`
- keys, tokens, Terraform state, or local cache data
