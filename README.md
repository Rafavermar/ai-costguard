# AI Cost Guard

AI Cost Guard is a local-first proxy and guardrail kit for developers using coding agents in VS Code, mainly Cline and Claude Code. It helps reduce token usage, enforce local budgets, block risky secret access, and keep usage metadata in SQLite.

```text
VS Code
  Cline       -> http://127.0.0.1:4040/v1 -> Cost Guard -> OpenAI-compatible upstream
  Claude Code -> http://127.0.0.1:4040    -> Cost Guard -> Anthropic-compatible upstream
```

## What It Does

- Runs a localhost proxy on `127.0.0.1:4040`.
- Supports Cline via OpenAI-compatible `/v1/chat/completions`.
- Supports Claude Code via Anthropic-compatible `/v1/messages`.
- Maps model aliases: `cg-cheap`, `cg-standard`, `cg-strong`, `cg-sonnet`.
- Enforces daily/monthly budgets with `warn`, `block-premium`, or `block-all`.
- Blocks secret-like paths and commands such as `cat .env`.
- Rewrites noisy commands such as full `git diff` and `find .`.
- Logs usage metadata to local SQLite without prompts or responses by default.
- Installs reversible Claude Code hooks and safe commands.

## What It Does Not Do

- It does not replace Cline, Claude Code, or your corporate GenAI backends.
- It does not require Docker, Kubernetes, Postgres, or a cloud dashboard.
- It does not expose the proxy outside localhost unless you explicitly choose another host.
- It does not modify project repos unless you run `costguard attach`.
- It does not store real API keys in Git.

## Install

From a GitHub repo:

```bash
pipx install git+https://github.com/<user-or-org>/ai-costguard.git
```

For local development:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

## Quickstart

```bash
costguard setup --tool both --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard doctor
costguard start
costguard cline-config
```

Then configure upstream endpoints and model names in:

```text
~/.costguard/.env
```

## Cline Configuration

Run:

```bash
costguard cline-config
```

Paste the printed values into Cline:

```text
Provider: OpenAI Compatible
Base URL: http://127.0.0.1:4040/v1
API Key: sk-costguard-local
Model ID: cg-standard
```

## Useful Commands

```bash
costguard status
costguard doctor
costguard use cheap|standard|strong|sonnet
costguard budget status
costguard budget set --daily 5 --monthly 100
costguard budget mode warn|block-premium|block-all
costguard rules test "cat .env"
costguard rules test "git diff"
costguard usage today
costguard cache status
costguard headroom status
costguard uninstall
```

## Safe Local Development

Use isolated paths so setup and uninstall never touch your real home configuration:

```powershell
$env:COSTGUARD_HOME = "$(Get-Location)\.tmp\costguard"
$env:COSTGUARD_CLAUDE_HOME = "$(Get-Location)\.tmp\claude"
costguard setup --tool both --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
costguard doctor
costguard rules test "cat .env"
costguard uninstall --yes
```

## Documentation

- `docs/RUNBOOK.md`: step-by-step operating guide.
- `docs/ARCHITECTURE.md`: local proxy architecture and data flow.
- `docs/SECURITY.md`: security model and local data handling.
- `docs/TROUBLESHOOTING.md`: common failures and fixes.

## License

MIT. See `LICENSE`.
