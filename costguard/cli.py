from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import __version__, budget as budget_mod, cache as cache_mod, cline, config, doctor as doctor_mod
from . import headroom as headroom_mod, paths, proxy, rules, usage as usage_mod
from . import pricing as pricing_mod
from .claude_code import update_anthropic_model
from .install import attach_project, setup_costguard
from .uninstall import uninstall_costguard


app = typer.Typer(no_args_is_help=True)
budget_app = typer.Typer(help="Manage budgets.")
rules_app = typer.Typer(help="Inspect and test rules.")
usage_app = typer.Typer(help="Show local usage metadata.")
cache_app = typer.Typer(help="Manage optional cache.")
headroom_app = typer.Typer(help="Manage optional Headroom integration.")
pricing_app = typer.Typer(help="Manage model pricing catalog.")
app.add_typer(budget_app, name="budget")
app.add_typer(rules_app, name="rules")
app.add_typer(usage_app, name="usage")
app.add_typer(cache_app, name="cache")
app.add_typer(headroom_app, name="headroom")
app.add_typer(pricing_app, name="pricing")
console = Console()


@app.callback()
def main(version: bool = typer.Option(False, "--version", help="Show version.", is_eager=True)) -> None:
    if version:
        console.print(__version__)
        raise typer.Exit()


@app.command()
def setup(
    tool: str = typer.Option("both", "--tool", help="cline, claude-code, or both."),
    daily_budget: float = typer.Option(5.0, "--daily-budget"),
    monthly_budget: float = typer.Option(100.0, "--monthly-budget"),
    budget_mode: str = typer.Option("warn", "--budget-mode"),
    non_interactive: bool = typer.Option(False, "--non-interactive"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    openai_upstream_base_url: Optional[str] = typer.Option(None, "--openai-upstream-base-url"),
    anthropic_upstream_base_url: Optional[str] = typer.Option(None, "--anthropic-upstream-base-url"),
    openai_model_cheap: Optional[str] = typer.Option(None, "--openai-model-cheap"),
    openai_model_standard: Optional[str] = typer.Option(None, "--openai-model-standard"),
    openai_model_strong: Optional[str] = typer.Option(None, "--openai-model-strong"),
    anthropic_model_cheap: Optional[str] = typer.Option(None, "--anthropic-model-cheap"),
    anthropic_model_standard: Optional[str] = typer.Option(None, "--anthropic-model-standard"),
    anthropic_model_strong: Optional[str] = typer.Option(None, "--anthropic-model-strong"),
    cache_mode: str = typer.Option("disabled", "--cache-mode", help="disabled, basic, or semantic."),
    headroom_enabled: bool = typer.Option(False, "--headroom/--no-headroom"),
    autostart_enabled: bool = typer.Option(False, "--autostart/--no-autostart"),
) -> None:
    if cache_mode not in {"disabled", "basic", "semantic"}:
        console.print("[red]Cache mode must be disabled, basic, or semantic.[/red]")
        raise typer.Exit(code=1)
    try:
        result = setup_costguard(
            tool=tool,
            daily_budget=daily_budget,
            monthly_budget=monthly_budget,
            budget_mode=budget_mode,
            non_interactive=non_interactive,
            dry_run=paths.dry_run_enabled(dry_run),
            openai_upstream_base_url=openai_upstream_base_url,
            anthropic_upstream_base_url=anthropic_upstream_base_url,
            openai_model_cheap=openai_model_cheap,
            openai_model_standard=openai_model_standard,
            openai_model_strong=openai_model_strong,
            anthropic_model_cheap=anthropic_model_cheap,
            anthropic_model_standard=anthropic_model_standard,
            anthropic_model_strong=anthropic_model_strong,
            cache_mode=cache_mode,
            headroom_enabled=headroom_enabled,
            autostart_enabled=autostart_enabled,
        )
    except RuntimeError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"Cost Guard home: {result['home']}")
    if result["dry_run"]:
        console.print("Dry run only. Planned paths:")
        for item in result["planned"]:
            console.print(f"- {item}")
    else:
        console.print("Setup complete.")
    console.print("Next steps: costguard start | costguard doctor | costguard cline-config")


@app.command()
def start(
    host: Optional[str] = typer.Option(None, "--host"),
    port: Optional[int] = typer.Option(None, "--port"),
) -> None:
    env = config.load_env(paths.costguard_home())
    host = host or env.get("COSTGUARD_HOST", "127.0.0.1")
    port = port or int(env.get("COSTGUARD_PORT", "4040") or 4040)
    if host != "127.0.0.1":
        console.print(f"[yellow]WARNING[/yellow] listening on {host}; default is 127.0.0.1.")
    proxy.start_proxy(host=host, port=port)


@app.command()
def stop() -> None:
    console.print(proxy.stop_from_pid())


@app.command()
def status() -> None:
    home = paths.costguard_home()
    settings = config.load_settings(home)
    env = config.load_env(home)
    table = Table("Item", "Value")
    table.add_row("Proxy", f"{env.get('COSTGUARD_HOST')}:{env.get('COSTGUARD_PORT')}")
    table.add_row("Tools", ", ".join(k for k, v in settings.get("tools", {}).items() if v) or "none")
    table.add_row("Active model", escape(str(settings.get("active_model", "cg-standard"))))
    table.add_row("Budget", escape(str(settings.get("budget", {}))))
    table.add_row("Cache", escape(config.cache_mode(home)))
    table.add_row("Headroom", escape(str(config.headroom_enabled(home))))
    table.add_row("Config", escape(str(paths.settings_path(home))))
    table.add_row("SQLite", escape(str(paths.db_path(home))))
    table.add_row("Logs", escape(str(paths.logs_dir(home))))
    console.print(table)


@app.command()
def doctor() -> None:
    checks = doctor_mod.run_checks()
    table = Table("Level", "Check", "Detail")
    for check in checks:
        style = {"OK": "green", "WARN": "yellow", "ERROR": "red"}.get(check.level, "")
        table.add_row(f"[{style}]{check.level}[/{style}]", escape(check.name), escape(check.detail))
    console.print(table)
    if doctor_mod.has_errors(checks):
        raise typer.Exit(code=1)


@app.command("cline-config")
def cline_config() -> None:
    console.print(cline.config_text())


@app.command("use")
def use_model(alias: str = typer.Argument(..., help="cheap, standard, strong, or cg-* alias.")) -> None:
    try:
        settings = config.set_active_model(alias)
    except ValueError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc
    active = settings["active_model"]
    update_anthropic_model(active)
    console.print(f"Active model: {active}")


@app.command()
def attach(
    project: str = typer.Option(..., "--project"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    result = attach_project(project, dry_run=paths.dry_run_enabled(dry_run))
    if result["dry_run"]:
        console.print(f"Would create {result['settings_path']}")
    else:
        console.print(f"Created {result['settings_path']}")


@app.command()
def uninstall(
    purge: bool = typer.Option(False, "--purge"),
    yes: bool = typer.Option(False, "--yes"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    try:
        result = uninstall_costguard(purge=purge, yes=yes, dry_run=paths.dry_run_enabled(dry_run))
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"Proxy: {result['stop']}")
    console.print(f"Claude Code: {result['claude']}")
    console.print("Cline must be reverted manually to its previous provider/base URL.")
    if result["purged"]:
        console.print(f"Purged {result['home']}")
    else:
        console.print(f"Kept Cost Guard home: {result['home']}")


@budget_app.command("status")
def budget_status() -> None:
    data = budget_mod.budget_status(paths.costguard_home())
    table = Table("Metric", "Value")
    for key, value in data.items():
        table.add_row(escape(key.replace("_", " ")), escape(f"{value:.6f}" if isinstance(value, float) else str(value)))
    console.print(table)


@budget_app.command("set")
def budget_set(
    daily: Optional[float] = typer.Option(None, "--daily"),
    monthly: Optional[float] = typer.Option(None, "--monthly"),
) -> None:
    config.update_budget(daily=daily, monthly=monthly)
    console.print("Budget updated.")


@budget_app.command("mode")
def budget_mode(mode: str = typer.Argument(..., help="warn, block-premium, or block-all")) -> None:
    if mode not in {"warn", "block-premium", "block-all"}:
        console.print("[red]Mode must be warn, block-premium, or block-all.[/red]")
        raise typer.Exit(code=1)
    config.update_budget(mode=mode)
    console.print(f"Budget mode: {mode}")


@rules_app.command("list")
def rules_list() -> None:
    table = Table("Origin", "Type", "Rule")
    for row in rules.list_rules():
        table.add_row(escape(row["origin"]), escape(row["type"]), escape(row["rule"]))
    console.print(table)


@rules_app.command("edit")
def rules_edit() -> None:
    user_rules = paths.rules_dir() / "user.yaml"
    editor = __import__("os").environ.get("EDITOR") or __import__("os").environ.get("VISUAL")
    if not editor:
        console.print(str(user_rules))
        return
    __import__("subprocess").run([editor, str(user_rules)], check=False)


@rules_app.command("test")
def rules_test(command: str = typer.Argument(...)) -> None:
    result = rules.evaluate_command(command)
    if result.action == "block":
        console.print(f"BLOCK: {result.reason}")
    elif result.action == "rewrite":
        console.print(f"REWRITE: {result.command}")
        console.print(f"Reason: {result.reason}")
    else:
        console.print("ALLOW")


@usage_app.command("today")
def usage_today() -> None:
    _print_usage(usage_mod.summary("today"))


@usage_app.command("month")
def usage_month() -> None:
    _print_usage(usage_mod.summary("month"))


def _print_usage(data: dict[str, object]) -> None:
    table = Table("Metric", "Value")
    for key, value in data.items():
        table.add_row(escape(key.replace("_", " ")), escape(str(value)))
    console.print(table)


@cache_app.command("status")
def cache_status() -> None:
    _print_cache(cache_mod.status())


@cache_app.command("enable")
def cache_enable(mode: str = typer.Option(..., "--mode", help="basic or semantic")) -> None:
    _print_cache(cache_mod.enable(mode))


@cache_app.command("disable")
def cache_disable() -> None:
    _print_cache(cache_mod.disable())


@cache_app.command("clear")
def cache_clear(
    responses: bool = typer.Option(False, "--responses", "--responses-only", help="Clear exact-match response cache only."),
    pricing: bool = typer.Option(False, "--pricing", "--pricing-only", help="Clear pricing catalog cache only."),
    vectors: bool = typer.Option(False, "--vectors", "--vectors-only", help="Clear semantic/vector cache only."),
    expired: bool = typer.Option(False, "--expired", help="Clear expired response cache entries only."),
) -> None:
    _print_cache(
        cache_mod.clear(
            responses_only=responses,
            pricing_only=pricing,
            vectors_only=vectors,
            expired_only=expired,
        )
    )


@cache_app.command("inspect")
def cache_inspect(limit: int = typer.Option(20, "--limit", help="Maximum response cache metadata entries to show.")) -> None:
    _print_cache(cache_mod.inspect(limit=limit))


def _print_cache(data: dict[str, object]) -> None:
    table = Table("Metric", "Value")
    for key, value in data.items():
        table.add_row(escape(key.replace("_", " ")), escape(str(value)))
    console.print(table)


@headroom_app.command("status")
def headroom_status() -> None:
    _print_headroom(headroom_mod.status())


@headroom_app.command("enable")
def headroom_enable() -> None:
    try:
        _print_headroom(headroom_mod.enable())
    except RuntimeError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc


@headroom_app.command("disable")
def headroom_disable() -> None:
    _print_headroom(headroom_mod.disable())


@headroom_app.command("test")
def headroom_test(
    sample: str = typer.Option("repeated", "--sample", help="short, repeated, or long-context."),
    client: str = typer.Option("cline", "--client", help="cline or claude-code."),
    model: str = typer.Option("cg-active", "--model", help="Cost Guard model alias to resolve for the sample."),
    force: bool = typer.Option(
        False,
        "--force",
        help="Diagnostic only: run the adapter even if Headroom is disabled in local config.",
    ),
) -> None:
    try:
        _print_headroom(headroom_mod.diagnostic(sample=sample, client=client, model=model, force_enabled=force))
    except ValueError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc


def _print_headroom(data: dict[str, object]) -> None:
    table = Table("Metric", "Value")
    for key, value in data.items():
        table.add_row(escape(key.replace("_", " ")), escape(str(value)))
    console.print(table)


@pricing_app.command("status")
def pricing_status() -> None:
    _print_pricing(pricing_mod.status())


@pricing_app.command("configure")
def pricing_configure(
    endpoint: str = typer.Option(..., "--endpoint", help="Model catalog endpoint to store in the local Cost Guard .env."),
    api_key_env: Optional[str] = typer.Option(
        None,
        "--api-key-env",
        help="Shell or local .env variable containing the pricing API key. The key itself is not stored.",
    ),
    auth_header: str = typer.Option("x-api-key", "--auth-header", help="Authentication header name."),
    auth_scheme: Optional[str] = typer.Option(None, "--auth-scheme", help="Optional auth scheme prefix."),
) -> None:
    try:
        _print_pricing(
            pricing_mod.configure(
                endpoint=endpoint,
                api_key_env=api_key_env,
                auth_header=auth_header,
                auth_scheme=auth_scheme,
            )
        )
    except Exception as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc


@pricing_app.command("refresh")
def pricing_refresh(
    endpoint: Optional[str] = typer.Option(
        None,
        "--endpoint",
        help="Model catalog endpoint. Overrides COSTGUARD_PRICING_URL for this run.",
    ),
    api_key_env: Optional[str] = typer.Option(
        None,
        "--api-key-env",
        help="Shell or local .env variable containing the pricing API key. The key is never printed or cached.",
    ),
    auth_header: Optional[str] = typer.Option(
        None,
        "--auth-header",
        help="Authentication header name, for example x-api-key.",
    ),
    auth_scheme: Optional[str] = typer.Option(
        None,
        "--auth-scheme",
        help="Optional auth scheme prefix, for example Bearer. Leave empty for raw API keys.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Fetch and parse pricing without writing pricing.yaml or models.json.",
    ),
    timeout: float = typer.Option(30.0, "--timeout", help="HTTP timeout in seconds."),
) -> None:
    try:
        _print_pricing(
            pricing_mod.refresh(
                endpoint=endpoint,
                api_key_env=api_key_env,
                auth_header=auth_header,
                auth_scheme=auth_scheme,
                dry_run=dry_run,
                timeout=timeout,
            )
        )
    except Exception as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc


def _print_pricing(data: dict[str, object]) -> None:
    table = Table("Metric", "Value")
    for key, value in data.items():
        table.add_row(escape(key.replace("_", " ")), escape(str(value)))
    console.print(table)
