# Update ai-costguard On A Work PC

This procedure updates a local `ai-costguard` checkout on a corporate PC when the code is distributed through a company fork.

Recommended flow:

```text
Personal/original repo updated
  -> Sync fork in company GitHub
  -> git pull in local company checkout
  -> uv sync
  -> offline validations
```

## 1. Goal

Update `ai-costguard` on a corporate PC without modifying client repositories, without touching real local configuration unnecessarily, and without consuming LLM tokens.

The validations in this document are offline: they check the CLI, rules, environment, tests, and local state. They should not call Cline, Claude Code, or Generative Engine.

## 2. Assumptions

- The company local checkout is in a folder similar to:

```text
C:\Users\<user>\...\Github\AI\ai-costguard
```

- `origin` points to the company fork, not necessarily to the personal/original repo.
- The company fork is synchronized from GitHub web using `Sync fork`.
- The project is managed with `uv`.
- Do not use `pip` directly for this update flow.
- Do not run this procedure inside a client repository such as `databricks-free-lab`.

## 3. Sync The Company Fork

1. Open the company fork of `ai-costguard` in GitHub.
2. Click `Sync fork`.
3. Click `Update branch`.
4. Confirm that the fork is up to date with the personal/original repo.

You do not need to configure a local upstream remote for this flow. The fork is synchronized from GitHub web to keep the work-PC procedure simple and less error-prone.

## 4. Update The Local Checkout

Open PowerShell and move to the local `ai-costguard` checkout, not to a client repo:

```powershell
Set-Location "PATH_TO_REPO\ai-costguard"

git remote -v
git status
git branch --show-current

git fetch origin --prune
git pull --ff-only origin main
git log --oneline -10
```

Expected evidence:

- `origin` points to the company fork.
- The active branch is `main`.
- `git status` shows no pending local changes before the update.
- `git pull --ff-only origin main` completes without a manual merge.
- `git log --oneline -10` shows the expected recent commits.

If `git pull --ff-only` fails because of local changes, do not run `git reset --hard` without a backup and without understanding which changes would be lost.

## 5. Stop CostGuard Before Updating The Environment

Before recreating `.venv`, stop CostGuard if it was running:

```powershell
costguard stop

Get-Process python,uv,costguard -ErrorAction SilentlyContinue | Select-Object Name,Id,Path
```

How to interpret this:

- If no processes are returned, you can continue.
- If `python`, `costguard`, or `uv` processes are returned, they may be locking `.venv`.
- Do not kill processes blindly. Check the `Path` value and confirm they belong to this repo or to CostGuard before closing them.

## 6. Recreate A Clean uv Environment

From the local `ai-costguard` checkout:

```powershell
Remove-Item -Recurse -Force .\.venv

uv sync --extra dev --extra headroom
```

We recreate the environment cleanly because real work-PC testing showed that it avoids inconsistent environments, `missing RECORD file`, half-installed packages, and `Access denied` errors.

Expected evidence:

- Output equivalent to `Creating virtual environment at: .venv`.
- Packages are installed from the local project.
- `ai-costguard` is installed from a path like `file:///.../ai-costguard`.
- `headroom-ai` is installed when the `headroom` extra is used.
- No `missing RECORD file` warnings appear.
- No `Access denied` errors appear.

If `Remove-Item` fails, go back to the previous section and check for live processes.

## 7. Validate The Updated CLI

```powershell
uv run costguard --help
```

Expected commands:

- `setup`
- `start`
- `stop`
- `status`
- `doctor`
- `cline-config`
- `budget`
- `rules`
- `usage`
- `cache`
- `headroom`
- `pricing`

If `costguard` is not available globally, use `uv run costguard ...` from inside the repo and avoid mixing it with older global installations.

## 8. Offline Validations Without Consuming Tokens

These validations should not call LLMs or consume Generative Engine quota:

```powershell
uv run pytest

uv run costguard rules test "cat .env"
uv run costguard rules test "git diff"
uv run costguard rules test "find ."

uv run costguard pricing --help
uv run costguard pricing status

uv run costguard headroom status
uv run costguard cache status
```

Expected evidence:

- `pytest` passes.
- `cat .env` is blocked.
- `git diff` and `find .` are rewritten to smaller commands.
- `pricing status`, `headroom status`, and `cache status` show local state.

Do not test Cline against the model during this phase if quota is exhausted or if you only need to validate the local update.

## 9. Optional Isolated Validation

To validate `setup` without touching `~/.costguard`, `~/.claude`, or real Claude Code configuration, use temporary paths inside the repo:

```powershell
$env:COSTGUARD_HOME = "$(Get-Location)\.tmp\costguard"
$env:COSTGUARD_CLAUDE_HOME = "$(Get-Location)\.tmp\claude"

uv run costguard setup --tool cline --daily-budget 5 --monthly-budget 100 --budget-mode warn --non-interactive
uv run costguard doctor
uv run costguard status
uv run costguard cline-config
```

This isolated validation should not modify real Claude Code configuration. With `--tool cline`, CostGuard only prints Cline configuration and keeps the test inside `COSTGUARD_HOME`.

## 10. What Not To Do

- Do not run this procedure inside client repositories.
- Do not use `pip install` directly unless a specific runbook says so.
- Do not run `git reset --hard` without a backup.
- Do not edit `~/.claude/settings.json` without explicit confirmation.
- Do not paste secrets into terminals, issues, logs, or chats.
- Do not test Cline against the model if Generative Engine quota is exhausted.
- Do not use `Retry` in Cline when `payload blocked by secret filter` appears; use `Start New Task`.

## 11. Troubleshooting

### Case: `uv sync` Fails With `Access denied`

Stop CostGuard:

```powershell
costguard stop
```

Check processes:

```powershell
Get-Process python,uv,costguard -ErrorAction SilentlyContinue | Select-Object Name,Id,Path
```

If there are no relevant processes, delete `.venv` and repeat `uv sync`:

```powershell
Remove-Item -Recurse -Force .\.venv
uv sync --extra dev --extra headroom
```

### Case: `missing RECORD file` Warning

Recreate `.venv` with `uv`:

```powershell
Remove-Item -Recurse -Force .\.venv
uv sync --extra dev --extra headroom
```

### Case: `pip` Does Not Exist In `.venv`

This is expected when the environment is managed with `uv`. Use:

```powershell
uv run costguard --help
uv run pytest
```

### Case: `429 true` From Cline

This is usually a Generative Engine provider limit or quota issue, not necessarily a CostGuard block.

Possible actions:

- Wait for quota reset.
- Change credentials or tier if applicable.
- Validate offline with `uv run pytest` and `costguard` commands without calling the model.

### Case: `payload blocked by secret filter`

This can be caused by accumulated Cline context.

Recommended actions:

- Open `Start New Task`.
- Try a minimal prompt such as `Say OK`.
- Do not use `Retry` as the first diagnostic step because it may resend the same accumulated context.

## 12. Final Checklist

- [ ] Company fork synchronized from GitHub.
- [ ] Local checkout updated with `git pull --ff-only`.
- [ ] `costguard stop` executed.
- [ ] No `python`, `uv`, or `costguard` processes are locking `.venv`.
- [ ] `.venv` recreated with `uv`.
- [ ] `uv run costguard --help` shows `pricing`, `headroom`, and `cache`.
- [ ] `pytest` passes.
- [ ] `rules test` works.
- [ ] `pricing status` works.
- [ ] No client repositories were touched.
- [ ] No LLM tokens were consumed during offline validations.
