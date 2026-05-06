"""Typer CLI: `aima probe`, `aima detect`, `aima serve`, `aima demo`."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from .demo import seed_demo
from .detector import detect_incidents
from .probe import Vantage, run_batch
from .store import Store
from .types import (
    IncidentSeverity,
    ProbeProfile,
    TransportKind,
    utcnow,
)

app = typer.Typer(help="AiMa Auto-Healer prototype")
console = Console()


def _load_store(db: Path) -> Store:
    return Store(db)


def _vantage(name: str = "local-vm") -> Vantage:
    return Vantage(name=name)


@app.command("init")
def init_cmd(
    db: Path = typer.Option(Path("aima.db"), help="SQLite database path"),
    profiles: Path | None = typer.Option(None, help="JSON file with a list of ProbeProfile dicts"),
) -> None:
    """Initialize DB and load profiles from JSON."""

    store = _load_store(db)
    if profiles is None:
        # Sane defaults: probe a few public TLS endpoints commonly used as REALITY 'dest' targets.
        defaults = [
            ProbeProfile(
                id="cloudflare-tls",
                label="Cloudflare TLS baseline",
                kind=TransportKind.DIRECT_TLS,
                host="www.cloudflare.com",
                sni="www.cloudflare.com",
            ),
            ProbeProfile(
                id="apple-tls",
                label="Apple TLS baseline",
                kind=TransportKind.DIRECT_TLS,
                host="www.apple.com",
                sni="www.apple.com",
            ),
            ProbeProfile(
                id="cloudflare-https",
                label="Cloudflare HTTPS GET",
                kind=TransportKind.DIRECT_HTTPS,
                host="www.cloudflare.com",
                sni="www.cloudflare.com",
            ),
            ProbeProfile(
                id="cloudflare-dns",
                label="Cloudflare DNS A",
                kind=TransportKind.DNS,
                host="www.cloudflare.com",
            ),
        ]
        for p in defaults:
            store.upsert_profile(p)
        console.print(f"[green]inserted {len(defaults)} default profiles[/]")
        return
    payload = json.loads(profiles.read_text())
    n = 0
    for raw in payload:
        store.upsert_profile(ProbeProfile.model_validate(raw))
        n += 1
    console.print(f"[green]inserted {n} profiles from {profiles}[/]")


@app.command("probe")
def probe_cmd(
    db: Path = typer.Option(Path("aima.db")),
    vantage_name: str = typer.Option("local-vm", help="Name of this vantage point"),
    concurrency: int = typer.Option(16),
) -> None:
    """Run all profiles once from this vantage and store reports."""

    store = _load_store(db)
    profiles = store.list_profiles()
    if not profiles:
        console.print("[red]no profiles in DB. Run `aima init` first.[/]")
        raise typer.Exit(1)
    reports = asyncio.run(run_batch(profiles, _vantage(vantage_name), concurrency=concurrency))
    for r in reports:
        store.insert_report(r)
    table = Table(title=f"Probe results from {vantage_name}")
    table.add_column("profile")
    table.add_column("kind")
    table.add_column("ok")
    table.add_column("block_type")
    table.add_column("rtt_ms")
    table.add_column("error")
    by_id = {p.id: p for p in profiles}
    for r in reports:
        kind = by_id[r.profile_id].kind.value
        table.add_row(
            r.profile_id,
            kind,
            "[green]yes[/]" if r.success else "[red]no[/]",
            r.block_type.value,
            f"{r.rtt_ms:.0f}" if r.rtt_ms else "-",
            (r.error or "")[:60],
        )
    console.print(table)


@app.command("detect")
def detect_cmd(
    db: Path = typer.Option(Path("aima.db")),
    window_minutes: int = typer.Option(30),
) -> None:
    """Run the incident detector across the last <window_minutes> of reports."""

    store = _load_store(db)
    since = utcnow() - timedelta(minutes=window_minutes)
    reports = store.reports_since(since=since)
    incidents = detect_incidents(reports, window_minutes=window_minutes)
    for inc in incidents:
        store.upsert_incident(inc)

    severity_color = {
        IncidentSeverity.CRITICAL: "bold red",
        IncidentSeverity.HIGH: "red",
        IncidentSeverity.MEDIUM: "yellow",
        IncidentSeverity.LOW: "blue",
        IncidentSeverity.INFO: "dim",
    }

    table = Table(title=f"Incidents over last {window_minutes}m  (reports: {len(reports)})")
    table.add_column("id")
    table.add_column("severity")
    table.add_column("block_type")
    table.add_column("profile")
    table.add_column("vantage")
    table.add_column("fail%")
    table.add_column("conf")
    table.add_column("recipes")
    for inc in incidents:
        table.add_row(
            inc.id,
            f"[{severity_color[inc.severity]}]{inc.severity.value}[/]",
            inc.block_type.value,
            inc.profile_id or "-",
            inc.vantage or "-",
            f"{inc.failure_rate:.0%}",
            f"{inc.confidence:.2f}",
            ", ".join(inc.suggested_recipes[:3]),
        )
    console.print(table)


@app.command("demo")
def demo_cmd(
    db: Path = typer.Option(Path("aima-demo.db"), help="Use a separate demo DB"),
    minutes: int = typer.Option(45, help="Synthetic timeline length"),
) -> None:
    """Seed a synthetic timeline showing SNI block + QUIC drop + REALITY detection."""

    if db.exists():
        db.unlink()
    store = _load_store(db)
    seed_demo(store, minutes=minutes)
    incidents = detect_incidents(
        store.reports_since(since=utcnow() - timedelta(minutes=minutes)),
        window_minutes=minutes,
    )
    for inc in incidents:
        store.upsert_incident(inc)
    table = Table(title=f"Demo incidents (synthetic, {minutes}m timeline)")
    table.add_column("severity")
    table.add_column("block_type")
    table.add_column("profile")
    table.add_column("vantage")
    table.add_column("fail%")
    table.add_column("conf")
    table.add_column("summary")
    for inc in incidents:
        table.add_row(
            inc.severity.value,
            inc.block_type.value,
            inc.profile_id or "-",
            inc.vantage or "-",
            f"{inc.failure_rate:.0%}",
            f"{inc.confidence:.2f}",
            inc.summary[:80],
        )
    console.print(table)
    console.print(
        "\n[dim]Recipes the (future) mutation engine would try, in priority order:[/]"
    )
    for inc in incidents:
        console.print(
            f"  • {inc.block_type.value} @ {inc.vantage}: " + ", ".join(inc.suggested_recipes)
        )


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("0.0.0.0"),
    port: int = typer.Option(8765),
    db: Path = typer.Option(Path("aima.db")),
    no_scheduler: bool = typer.Option(False, "--no-scheduler"),
) -> None:
    """Run the FastAPI server with the 24/7 scheduler attached."""

    import os

    os.environ["AIMA_DB"] = str(db)
    from . import api as api_mod

    api_mod.app = api_mod.create_app(db_path=str(db), run_scheduler=not no_scheduler)
    uvicorn.run(api_mod.app, host=host, port=port, log_level="info")


@app.command("ls-profiles")
def list_profiles_cmd(db: Path = typer.Option(Path("aima.db"))) -> None:
    store = _load_store(db)
    profiles = store.list_profiles()
    table = Table(title="Profiles")
    table.add_column("id")
    table.add_column("kind")
    table.add_column("host")
    table.add_column("sni")
    for p in profiles:
        table.add_row(p.id, p.kind.value, f"{p.host}:{p.port}", p.sni or "-")
    console.print(table)


if __name__ == "__main__":  # pragma: no cover
    app()
