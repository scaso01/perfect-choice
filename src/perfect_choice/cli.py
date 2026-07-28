"""Command-line interface for Perfect Choice."""

from __future__ import annotations

import argparse
import sys

from perfect_choice import __version__
from perfect_choice.templates import list_templates


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="perfect-choice",
        description="AHP-based decision-making CLI with structured forcing functions.",
    )
    parser.add_argument(
        "--version", action="version", version=f"perfect-choice {__version__}"
    )
    parser.add_argument(
        "--no-llm", action="store_true", help="Disable LLM features"
    )

    sub = parser.add_subparsers(dest="command")

    p_decide = sub.add_parser("decide", help="Interactive decision wizard")
    p_decide.add_argument(
        "--tier",
        choices=["quick", "standard", "deep"],
        help="Force a specific complexity tier",
    )
    p_decide.add_argument(
        "--template",
        choices=list_templates(),
        help="Use pre-built criteria from a template",
    )

    sub.add_parser("quick", help="Quick decision mode (forced quick tier)")

    p_import = sub.add_parser("import", help="Import decision from file")
    p_import.add_argument("file", help="Path to JSON or CSV file")
    p_import.add_argument(
        "--format", choices=["json", "csv"], dest="fmt",
        help="File format (auto-detected from extension if omitted)",
    )

    p_list = sub.add_parser("list", help="List past decisions")
    p_list.add_argument(
        "--status", choices=["completed", "in_progress", "abandoned"]
    )
    p_list.add_argument("--limit", type=int, default=20)

    p_review = sub.add_parser("review", help="Review a past decision")
    p_review.add_argument("id", help="Decision ID (or prefix)")

    p_replay = sub.add_parser("replay", help="Re-run with different weights")
    p_replay.add_argument("id", help="Decision ID (or prefix)")

    p_export = sub.add_parser("export", help="Export decision")
    p_export.add_argument("id", help="Decision ID (or prefix)")
    p_export.add_argument(
        "--format", choices=["json", "markdown"], default="markdown"
    )
    p_export.add_argument("--output", metavar="FILE", help="Output file")

    p_outcome = sub.add_parser("outcome", help="Record outcome for a past decision")
    p_outcome.add_argument("id", help="Decision ID (or prefix)")

    p_dash = sub.add_parser("dashboard", help="Launch Streamlit dashboard")
    p_dash.add_argument(
        "--port", type=int, default=8501, help="Port (default: 8501)"
    )

    sub.add_parser("brain-sync", help="Push all decisions to the memory webhook")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    from perfect_choice.config import Config

    config = Config(no_llm=True) if args.no_llm else Config()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "decide":
        from perfect_choice.interactive import run_wizard

        run_wizard(config, force_tier=args.tier, template=args.template)
        return 0

    if args.command == "quick":
        from perfect_choice.interactive import run_wizard

        run_wizard(config, force_tier="quick")
        return 0

    if args.command == "import":
        return _cmd_import(config, args)

    if args.command == "list":
        return _cmd_list(config, args)

    if args.command == "review":
        return _cmd_review(config, args)

    if args.command == "replay":
        return _cmd_replay(config, args)

    if args.command == "export":
        return _cmd_export(config, args)

    if args.command == "outcome":
        return _cmd_outcome(config, args)

    if args.command == "dashboard":
        return _cmd_dashboard(args)

    if args.command == "brain-sync":
        return _cmd_brain_sync(config, args)

    parser.print_help()
    return 0


def _cmd_dashboard(args) -> int:
    import os
    import subprocess
    import sys

    app_path = os.path.join(
        os.path.dirname(__file__), "dashboard", "app.py"
    )
    cmd = [
        sys.executable, "-m", "streamlit", "run", app_path,
        "--server.port", str(args.port),
        "--server.headless", "true",
    ]
    try:
        proc = subprocess.run(cmd)
        return proc.returncode
    except FileNotFoundError:
        from rich.console import Console
        Console().print(
            "[red]Streamlit not found. Install with: "
            "pip install perfect-choice[dashboard][/red]"
        )
        return 1


def _cmd_list(config, args) -> int:
    from rich.console import Console
    from rich.table import Table

    from perfect_choice.db import Database

    console = Console()
    with Database(config.db_path) as db:
        decisions = db.list_decisions(
            limit=args.limit, status_filter=args.status
        )
    if not decisions:
        console.print("[dim]No decisions found.[/dim]")
        return 0

    table = Table(title="Past Decisions")
    table.add_column("ID", style="cyan", max_width=8)
    table.add_column("Title")
    table.add_column("Tier", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Created")
    for d in decisions:
        table.add_row(
            d.id[:8], d.title, d.tier.value, d.status.value, d.created_at[:10]
        )
    console.print(table)
    return 0


def _cmd_review(config, args) -> int:
    from rich.console import Console

    from perfect_choice.db import Database
    from perfect_choice.interactive import display_results

    console = Console()
    with Database(config.db_path) as db:
        decision = db.get_decision_by_prefix(args.id)
    if decision is None:
        console.print(f"[red]No decision found matching '{args.id}'[/red]")
        return 1
    display_results(decision)
    return 0


def _cmd_replay(config, args) -> int:
    from rich.console import Console

    from perfect_choice.db import Database
    from perfect_choice.interactive import run_replay

    console = Console()
    with Database(config.db_path) as db:
        decision = db.get_decision_by_prefix(args.id)
    if decision is None:
        console.print(f"[red]No decision found matching '{args.id}'[/red]")
        return 1
    run_replay(config, decision)
    return 0


def _cmd_export(config, args) -> int:
    from rich.console import Console

    from perfect_choice.db import Database

    console = Console()
    with Database(config.db_path) as db:
        decision = db.get_decision_by_prefix(args.id)
    if decision is None:
        console.print(f"[red]No decision found matching '{args.id}'[/red]")
        return 1

    if args.format == "json":
        output = _export_json(decision)
    else:
        output = _export_markdown(decision)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        console.print(f"[green]Exported to {args.output}[/green]")
    else:
        console.print(output)
    return 0


def _export_json(decision) -> str:
    import json
    from dataclasses import asdict

    data = asdict(decision)
    data["tier"] = decision.tier.value
    data["status"] = decision.status.value
    for method, rankings in data.get("rankings", {}).items():
        for r in rankings:
            r["method"] = r["method"].value if hasattr(r["method"], "value") else r["method"]
    return json.dumps(data, indent=2, default=str)


def _export_markdown(decision) -> str:
    lines = [
        f"# {decision.title}",
        "",
        f"**Tier:** {decision.tier.value} | **Status:** {decision.status.value} | **Created:** {decision.created_at}",
        "",
    ]
    if decision.description:
        lines += [decision.description, ""]

    lines.append("## Criteria")
    lines.append("| Criterion | Weight | Type |")
    lines.append("|-----------|--------|------|")
    for c in decision.criteria:
        ctype = "Cost (lower=better)" if c.is_cost else "Benefit (higher=better)"
        lines.append(f"| {c.name} | {c.weight:.1%} | {ctype} |")
    lines.append("")

    lines.append("## Alternatives")
    for a in decision.alternatives:
        desc = f" — {a.description}" if a.description else ""
        lines.append(f"- {a.name}{desc}")
    lines.append("")

    for method, rankings in decision.rankings.items():
        lines.append(f"## Results ({method.upper()})")
        lines.append("| Rank | Alternative | Score |")
        lines.append("|------|-------------|-------|")
        for r in sorted(rankings, key=lambda x: x.rank):
            lines.append(f"| #{r.rank} | {r.alternative_name} | {r.score:.4f} |")
        lines.append("")

    if decision.llm_summary:
        lines += ["## Summary", "", decision.llm_summary, ""]
    if decision.llm_devils_advocate:
        lines += ["## Devil's Advocate", "", decision.llm_devils_advocate, ""]
    if decision.llm_bias_notes:
        lines += ["## Bias Analysis", "", decision.llm_bias_notes, ""]

    return "\n".join(lines)


def _cmd_import(config, args) -> int:
    import os

    from rich.console import Console

    from perfect_choice.db import Database
    from perfect_choice.importer import import_file

    console = Console()
    file_path = args.file

    if not os.path.isfile(file_path):
        console.print(f"[red]File not found: {file_path}[/red]")
        return 1

    try:
        decision = import_file(file_path, fmt=getattr(args, "fmt", None))
    except (ValueError, KeyError) as e:
        console.print(f"[red]Import error: {e}[/red]")
        return 1

    with Database(config.db_path) as db:
        db.save_decision(decision)

    console.print(f"[green]Imported: {decision.title}[/green]")
    console.print(f"  ID: {decision.id[:8]}")
    console.print(f"  Tier: {decision.tier.value}")
    console.print(f"  Alternatives: {len(decision.alternatives)}")
    console.print(f"  Criteria: {len(decision.criteria)}")

    for method, rankings in decision.rankings.items():
        top = sorted(rankings, key=lambda r: r.rank)[0]
        console.print(
            f"  {method.upper()} winner: [bold]{top.alternative_name}[/bold] "
            f"(score: {top.score:.4f})"
        )

    return 0


def _cmd_brain_sync(config, args) -> int:
    from rich.console import Console

    from perfect_choice.brain import (
        brain_url,
        store_decision_in_brain,
        update_brain_context,
    )
    from perfect_choice.db import Database

    console = Console()

    # Without a configured endpoint every POST fails, which used to be reported
    # as a red "Failed" per decision and read like a broken feature rather than
    # an unconfigured optional one.
    if not brain_url():
        console.print(
            "[yellow]No memory webhook configured, so there is nothing to sync."
            "[/yellow]\n"
            "[dim]Set PERFECT_CHOICE_BRAIN_URL to the endpoint that should "
            "receive your decisions, then run this again.[/dim]"
        )
        return 0

    with Database(config.db_path) as db:
        decisions = db.list_decisions(limit=100)

    if not decisions:
        console.print("[dim]No decisions to sync.[/dim]")
        return 0

    # Hydrate full decisions for brain storage
    stored = 0
    with Database(config.db_path) as db:
        full_decisions = []
        for d in decisions:
            full = db.get_decision(d.id)
            if full:
                full_decisions.append(full)
                if store_decision_in_brain(full):
                    stored += 1
                    console.print(f"  [green]Synced:[/green] {full.title}")
                else:
                    console.print(f"  [red]Failed:[/red] {full.title}")

    # Update context
    if update_brain_context(full_decisions):
        console.print("[green]Brain context updated.[/green]")

    console.print(f"\n[bold]Synced {stored}/{len(decisions)} decisions to brain.[/bold]")
    return 0


def _cmd_outcome(config, args) -> int:
    from datetime import datetime, timezone

    from rich.console import Console
    from rich.prompt import Confirm, IntPrompt, Prompt

    from perfect_choice.db import Database
    from perfect_choice.models import Outcome

    console = Console()
    with Database(config.db_path) as db:
        decision = db.get_decision_by_prefix(args.id)
        if not decision:
            console.print(f"[red]No decision found matching '{args.id}'[/red]")
            return 1

        existing = db.get_outcome(decision.id)
        if existing:
            console.print(
                f"[yellow]Outcome already recorded (rating: {existing.rating}/10)[/yellow]"
            )
            if not Confirm.ask("Overwrite?", default=False):
                return 0

        console.print(f"[bold]Recording outcome for: {decision.title}[/bold]")
        console.print(
            f"Alternatives: {', '.join(a.name for a in decision.alternatives)}"
        )

        # What did you actually choose?
        alt_names = [a.name for a in decision.alternatives]
        console.print("\nWhat did you actually choose?")
        for i, name in enumerate(alt_names, 1):
            console.print(f"  [{i}] {name}")
        choice_idx = IntPrompt.ask("Choice", default=1)
        choice_idx = max(1, min(len(alt_names), choice_idx))
        actual = alt_names[choice_idx - 1]

        # Satisfaction rating
        rating = IntPrompt.ask("Satisfaction (1-10)", default=5)
        rating = max(1, min(10, rating))

        # Notes
        notes = Prompt.ask("Notes (optional)", default="")

        outcome = Outcome(
            decision_id=decision.id,
            rating=rating,
            actual_choice=actual,
            notes=notes,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        db.save_outcome(outcome)

        # Show comparison: was the recommended choice what they picked?
        if decision.rankings:
            for method, results in decision.rankings.items():
                if results:
                    recommended = sorted(results, key=lambda r: r.rank)[0].alternative_name
                    match = (
                        "matched"
                        if recommended == actual
                        else f"differed (recommended: {recommended})"
                    )
                    console.print(f"  {method.upper()} recommendation {match}")

        console.print(f"\n[green]Outcome saved! Rating: {rating}/10[/green]")
    return 0
