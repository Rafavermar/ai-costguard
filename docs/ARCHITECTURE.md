# Architecture

AI Cost Guard is a local proxy plus a small set of local controls.

## Cline Flow

```text
VS Code -> Cline -> http://127.0.0.1:4040/v1 -> Cost Guard -> OpenAI-compatible upstream
```

Cline is configured manually:

```text
Provider: OpenAI Compatible
Base URL: http://127.0.0.1:4040/v1
API Key: sk-costguard-local
Model ID: cg-active
```

Cost Guard maps category aliases to upstream OpenAI-compatible model names from `.env`. `cg-active` resolves to the currently selected category; `cg-cheap`, `cg-standard`, and `cg-strong` are fixed categories.

## Claude Code Flow

```text
VS Code -> Claude Code -> http://127.0.0.1:4040 -> Cost Guard -> Anthropic-compatible upstream
```

Claude Code is configured by merging Cost Guard environment variables and hooks into `settings.json`. Existing settings are preserved and a backup is created first when the file is not already instrumented by Cost Guard.

## Where Cost Guard Lives

End-user files live under `~/.costguard`:

```text
.env
costguard.db
config/settings.yaml
config/pricing.yaml
rules/default.yaml
rules/user.yaml
hooks/
bin/
logs/
cache/
cache/responses/
cache/models.json
vector_cache/
backups/
```

For isolated development, `COSTGUARD_HOME` replaces `~/.costguard` and `COSTGUARD_CLAUDE_HOME` replaces `~/.claude`.

## Why It Does Not Touch Client Repos

Cost Guard is designed as an external local guard. It does not modify a project by default. The only project-level command is `costguard attach --project <name>`, which creates `.claude/settings.local.json` and excludes it via `.git/info/exclude`.

## Why SQLite, Not Postgres

SQLite is local, file-based, zero-service, and enough for usage metadata, budget checks, and audit events. It keeps setup simple and avoids Docker or managed infrastructure.

## Pricing Catalog

Cost Guard ships with fallback local cost estimates so the budget feature works without a corporate pricing service. For real deployments, configure `COSTGUARD_PRICING_URL` in `.env` and run `costguard pricing refresh`. The refresh reads a generic model catalog with fields such as `name`, `systemName`, `inputPrice`, and `outputPrice`, then stores normalized prices in `config/pricing.yaml`.

This is intentionally provider-neutral. A company can point Cost Guard at its own OpenAI-compatible, Anthropic-compatible, Bedrock-backed, or internal GenAI catalog as long as it exposes model names and input/output prices. Provider quotas and HTTP 429 responses remain upstream controls; Cost Guard budget remains a local policy.

The canonical fixed Cost Guard model aliases are `cg-cheap`, `cg-standard`, and `cg-strong`. They are local categories, not provider names. Each workstation maps those aliases to approved real model IDs in `.env`. The dynamic alias `cg-active` lets clients such as Cline follow the active category without editing client settings after each switch.

## Cache

Cache is optional and disabled by default.

`cache/models.json` is the pricing catalog cache written by `costguard pricing refresh`. It stores provider model metadata and prices, not API keys.

`cache/responses/` is the basic exact-match response cache. It becomes functional only when `COSTGUARD_CACHE_MODE=basic` and `COSTGUARD_CACHE_STORE_CONTENT=true`. Cost Guard hashes the request shape, model alias, resolved upstream model, endpoint identity, and payload to find identical requests. It does not store request headers or API keys. It skips streaming, tools/functions, multimodal/file inputs, secret-like payloads, and upstream errors.

Response cache limits are local and conservative by default:

```text
COSTGUARD_CACHE_TTL_SECONDS=86400
COSTGUARD_CACHE_MAX_ENTRIES=1000
COSTGUARD_CACHE_MAX_SIZE_MB=100
COSTGUARD_CACHE_EVICTION_POLICY=lru
```

Expired entries are removed during status/read/write/clear-expired paths. If the response cache exceeds entry or size limits, Cost Guard evicts entries using LRU by default. Pricing cache is not part of response-cache eviction and is not deleted by `costguard cache clear` unless the user explicitly passes `--pricing`.

`vector_cache/` is reserved for semantic cache work. The CLI can create and clear the folder, but embeddings/vector lookup are not active yet.

## Headroom

Headroom is an optional request compression layer. It is not a core dependency and is disabled by default. When enabled, Cost Guard imports the Python module installed by `headroom-ai` and applies it after the local secret filter and model alias mapping, but before budget estimation and upstream forwarding.

The preferred integration is the official library API:

- `compress(messages, model=...)`

Cost Guard passes the request `messages` list and the already-resolved upstream model name, then writes the returned `result.messages` back into the payload. For local/custom adapters, Cost Guard also supports these payload-level functions:

- `compress_payload(payload, ...)`
- `compress_request(payload, ...)`
- `transform_payload(payload, ...)`
- `apply(payload, ...)`

Payload-level functions may return a transformed payload dictionary or mutate the payload in place. Cost Guard passes optional `client` and `home` context when the adapter accepts it. If Headroom is enabled but no compatible adapter is available, the proxy fails with a clear local error rather than silently bypassing compression.

Headroom observability is metadata-only. Usage events store before/after input sizes, estimated before/after input tokens, estimated tokens saved, and reduction ratio. They do not store prompt or response content. `outputs_reduced` belongs to output limits and is not Headroom evidence.

## Proxy MVP

The proxy exposes:

- `/health`
- `/v1/chat/completions` for OpenAI-compatible Cline traffic
- `/v1/messages` for Anthropic-compatible Claude Code traffic

It validates the local API key, applies a basic secret filter, maps model aliases, optionally serves an exact-match response cache hit, checks budgets for cache misses, estimates cost from local pricing or fallback settings, forwards to the configured upstream, applies output limits where possible, and stores metadata in SQLite.

## Limitations

- Cost estimates are approximate.
- Streaming support is not implemented in the MVP.
- Semantic cache is scaffolded/experimental, not a full vector implementation. It should not be presented as functional until embeddings, vector storage, similarity thresholds, semantic hit/miss metrics, and tests exist.
- Headroom requires a compatible external adapter; no adapter is bundled in the base package.
- Cline still requires manual configuration.
- Upstream-specific edge cases may need adapter improvements.
