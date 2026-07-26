"""Rich interactive decision wizard."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich.tree import Tree

from perfect_choice.ahp import (
    build_comparison_matrix,
    compute_consistency_ratio,
    compute_priority_vector,
    required_comparisons,
)
from perfect_choice.config import Config
from perfect_choice.db import Database
from perfect_choice.llm import LLMClient
from perfect_choice.models import (
    Alternative,
    Criterion,
    Decision,
    DecisionStatus,
    PairwiseComparison,
    RankingResult,
    Score,
    SensitivityResult,
    Tier,
    detect_tier,
)
from perfect_choice.scoring import topsis_rank, wsm_rank
from perfect_choice.sensitivity import analyze_sensitivity

console = Console()

# Saaty pairwise labels: index -> (saaty_value, label)
PAIRWISE_LABELS = [
    (1.0, "Equal importance"),
    (3.0, "{a} slightly more important"),
    (5.0, "{a} moderately more important"),
    (7.0, "{a} strongly more important"),
    (9.0, "{a} overwhelmingly more important"),
    (1 / 3, "{b} slightly more important"),
    (1 / 5, "{b} moderately more important"),
    (1 / 7, "{b} strongly more important"),
    (1 / 9, "{b} overwhelmingly more important"),
]


def run_wizard(config: Config, force_tier: str | None = None, template: str | None = None) -> Decision:
    """Main interactive decision wizard."""
    console.print(
        Panel(
            "[bold]Perfect Choice[/bold] — Structured Decision Analysis",
            subtitle="Ctrl+C to abandon at any time",
            style="cyan",
        )
    )

    # Check LLM availability
    llm: LLMClient | None = None
    if not config.no_llm:
        llm = LLMClient(config)
        if llm.is_available():
            console.print("[dim]LLM connected — AI features enabled[/dim]\n")
        else:
            console.print("[dim]LLM unavailable — running in math-only mode[/dim]\n")
            llm = None

    try:
        # Step 1: Context
        title, description = _step_context()

        # Step 2: Alternatives
        alternatives = _step_alternatives()

        # Step 3: Criteria
        if template:
            from perfect_choice.templates import get_template

            tmpl = get_template(template)
            criteria_names = tmpl["criteria"]
            console.print(
                f"\n[bold]Using template: {template}[/bold] "
                f"({len(criteria_names)} criteria)\n"
            )
        else:
            criteria_names = _step_criteria(llm, f"{title}: {description}", alternatives)

        # Detect tier
        tier = _resolve_tier(force_tier, len(alternatives), len(criteria_names))
        console.print(f"\n[bold magenta]Tier: {tier.value.upper()}[/bold magenta]\n")

        # Quick tier: disable LLM thinking for speed
        if llm and tier == Tier.QUICK:
            llm.thinking = False

        # Step 4: Weights
        if tier == Tier.QUICK:
            criteria, comparisons, cr = _step_direct_weights(criteria_names)
        else:
            criteria, comparisons, cr = _step_pairwise(criteria_names)

        # Step 5: Scoring
        scores = _step_scoring(alternatives, criteria)

        # Step 6: Compute rankings
        alt_names = [a.name for a in alternatives]
        rankings: dict[str, tuple[RankingResult, ...]] = {}

        wsm_results = wsm_rank(alt_names, criteria, scores)
        rankings["wsm"] = tuple(wsm_results)

        if tier in (Tier.STANDARD, Tier.DEEP):
            topsis_results = topsis_rank(alt_names, criteria, scores)
            rankings["topsis"] = tuple(topsis_results)

        # Step 7: Sensitivity (Deep only)
        sensitivity: tuple[SensitivityResult, ...] = ()
        if tier == Tier.DEEP:
            console.print("\n[bold]Running sensitivity analysis...[/bold]")
            sens_results = analyze_sensitivity(
                alt_names, criteria, scores, wsm_rank
            )
            sensitivity = tuple(sens_results)

        # Step 8: LLM analysis
        llm_summary = ""
        llm_devils = ""
        llm_bias = ""
        if llm:
            console.print("[dim]Running AI analysis...[/dim]")
            ranked_for_llm = {
                m: list(r) for m, r in rankings.items()
            }
            llm_summary = llm.summarize_decision(
                title, ranked_for_llm, list(criteria),
                _format_sensitivity_brief(sensitivity) if sensitivity else "",
            )
            if tier in (Tier.STANDARD, Tier.DEEP):
                llm_bias = llm.detect_bias(list(criteria), list(scores))
            if tier == Tier.DEEP and wsm_results:
                llm_devils = llm.devils_advocate(
                    title, wsm_results, list(criteria)
                )

        # Build Decision
        now = datetime.now(timezone.utc).isoformat()
        decision = Decision(
            id=uuid.uuid4().hex,
            title=title,
            description=description,
            tier=tier,
            criteria=tuple(criteria),
            alternatives=tuple(alternatives),
            scores=tuple(scores),
            pairwise_comparisons=tuple(comparisons),
            rankings=rankings,
            sensitivity=sensitivity,
            consistency_ratio=cr,
            llm_summary=llm_summary,
            llm_devils_advocate=llm_devils,
            llm_bias_notes=llm_bias,
            created_at=now,
            completed_at=now,
            status=DecisionStatus.COMPLETED,
        )

        # Display results
        display_results(decision)

        # Save
        with Database(config.db_path) as db:
            db.save_decision(decision)
        console.print(
            f"\n[green]Saved![/green] ID: [cyan]{decision.id[:8]}[/cyan]"
        )

        # Optional memory webhook (fire-and-forget; no-op unless configured)
        from perfect_choice.brain import store_decision_in_brain

        store_decision_in_brain(decision)

        return decision

    except KeyboardInterrupt:
        console.print("\n[yellow]Decision abandoned.[/yellow]")
        raise SystemExit(0)


def run_replay(config: Config, decision: Decision) -> None:
    """Re-run a saved decision with new weights."""
    console.print(
        Panel(
            f"[bold]Replaying:[/bold] {decision.title}",
            style="cyan",
        )
    )
    console.print(
        f"Alternatives: {', '.join(a.name for a in decision.alternatives)}"
    )
    console.print(
        f"Criteria: {', '.join(c.name for c in decision.criteria)}\n"
    )

    criteria_names = [
        {"name": c.name, "description": c.description, "is_cost": c.is_cost}
        for c in decision.criteria
    ]

    if decision.tier == Tier.QUICK:
        criteria, comparisons, cr = _step_direct_weights(criteria_names)
    else:
        criteria, comparisons, cr = _step_pairwise(criteria_names)

    alt_names = [a.name for a in decision.alternatives]
    rankings: dict[str, tuple[RankingResult, ...]] = {}
    rankings["wsm"] = tuple(wsm_rank(alt_names, criteria, list(decision.scores)))
    if decision.tier in (Tier.STANDARD, Tier.DEEP):
        rankings["topsis"] = tuple(
            topsis_rank(alt_names, criteria, list(decision.scores))
        )

    # Show comparison
    console.print("\n[bold]New Rankings vs Original:[/bold]")
    _display_ranking_table(rankings)
    if decision.rankings:
        console.print("\n[dim]Original rankings:[/dim]")
        _display_ranking_table(decision.rankings)


def display_results(decision: Decision) -> None:
    """Display full decision results with Rich formatting."""
    console.print()
    console.print(
        Panel(
            f"[bold]{decision.title}[/bold]",
            subtitle=f"Tier: {decision.tier.value} | CR: {decision.consistency_ratio:.4f}"
            if decision.consistency_ratio is not None
            else f"Tier: {decision.tier.value}",
            style="green",
        )
    )

    # Criteria weights (plotext chart, fallback to Rich table)
    if not _try_plotext_weights(decision.criteria):
        _display_criteria_table(decision.criteria)

    # Rankings (plotext chart, fallback to Rich table)
    if not _try_plotext_ranking(decision.rankings):
        _display_ranking_table(decision.rankings)

    # Sensitivity (plotext chart, fallback to Rich tree)
    if decision.sensitivity:
        if not _try_plotext_sensitivity(decision.sensitivity):
            _display_sensitivity(decision.sensitivity)

    # LLM sections
    if decision.llm_summary:
        console.print(Panel(decision.llm_summary, title="Summary", style="blue"))
    if decision.llm_bias_notes:
        console.print(
            Panel(decision.llm_bias_notes, title="Bias Analysis", style="yellow")
        )
    if decision.llm_devils_advocate:
        console.print(
            Panel(
                decision.llm_devils_advocate,
                title="Devil's Advocate",
                style="red",
            )
        )


# ---------------------------------------------------------------------------
# Internal steps
# ---------------------------------------------------------------------------


def _resolve_tier(
    force_tier: str | None, n_alt: int, n_crit: int
) -> Tier:
    if force_tier:
        return Tier(force_tier)
    return detect_tier(n_alt, n_crit)


def _step_context() -> tuple[str, str]:
    """Get decision title and description."""
    console.print("[bold]Step 1: What are you deciding?[/bold]")
    title = Prompt.ask("  Decision title")
    description = Prompt.ask("  Brief description", default="")
    return title.strip(), description.strip()


def _step_alternatives() -> list[Alternative]:
    """Collect alternatives (minimum 2)."""
    console.print("\n[bold]Step 2: What are your options?[/bold]")
    console.print("  [dim]Enter one per line. Empty line when done (min 2).[/dim]")
    alternatives: list[Alternative] = []
    while True:
        label = f"  Option {len(alternatives) + 1}"
        name = Prompt.ask(label, default="")
        if not name.strip():
            if len(alternatives) >= 2:
                break
            console.print("  [red]Need at least 2 options.[/red]")
            continue
        alternatives.append(Alternative(name=name.strip()))
    return alternatives


def _step_criteria(
    llm: LLMClient | None,
    context: str,
    alternatives: list[Alternative],
) -> list[dict]:
    """Collect criteria, optionally with LLM suggestions.

    Returns list of {"name": str, "description": str, "is_cost": bool}.
    """
    console.print("\n[bold]Step 3: What matters to you?[/bold]")

    criteria: list[dict] = []

    # Template auto-matching from decision context
    from perfect_choice.templates import get_template, match_template

    matched = match_template(context)
    if matched:
        tmpl = get_template(matched)
        console.print(f"  [bold]Found template: {matched}[/bold] ({tmpl['description']})")
        for i, c in enumerate(tmpl["criteria"], 1):
            cost_tag = " [dim](cost)[/dim]" if c.get("is_cost") else ""
            console.print(f"    {i}. {c['name']}{cost_tag} — {c.get('description', '')}")
        if Confirm.ask("  Use template criteria?", default=True):
            return tmpl["criteria"]

    # LLM suggestions
    if llm:
        console.print("  [dim]Asking AI for suggestions...[/dim]")
        suggestions = llm.suggest_criteria(
            context, [a.name for a in alternatives]
        )
        if suggestions:
            console.print("  [bold]Suggested criteria:[/bold]")
            for i, s in enumerate(suggestions, 1):
                cost_tag = " [dim](cost)[/dim]" if s.get("is_cost") else ""
                console.print(
                    f"    {i}. {s['name']}{cost_tag} — {s.get('description', '')}"
                )
            if Confirm.ask("  Accept these suggestions?", default=True):
                criteria.extend(suggestions)
                console.print(f"  [green]Added {len(criteria)} criteria.[/green]")

    # Manual entry
    if not criteria:
        console.print(
            "  [dim]Enter criteria one per line. Empty line when done (min 1).[/dim]"
        )
    else:
        console.print(
            "  [dim]Add more criteria or press Enter to continue.[/dim]"
        )

    while True:
        name = Prompt.ask(f"  Criterion {len(criteria) + 1}", default="")
        if not name.strip():
            if criteria:
                break
            console.print("  [red]Need at least 1 criterion.[/red]")
            continue
        is_cost = Confirm.ask(
            f"  Is '{name.strip()}' a cost (lower = better)?", default=False
        )
        criteria.append(
            {"name": name.strip(), "description": "", "is_cost": is_cost}
        )

    return criteria


def _step_direct_weights(
    criteria_defs: list[dict],
) -> tuple[list[Criterion], list[PairwiseComparison], float | None]:
    """Quick mode: assign weights directly as percentages."""
    console.print("\n[bold]Step 4: How important is each criterion?[/bold]")
    console.print("  [dim]Assign percentage weights (must total 100).[/dim]")

    while True:
        weights: list[float] = []
        for cd in criteria_defs:
            w = IntPrompt.ask(f"  {cd['name']} (%)", default=100 // len(criteria_defs))
            weights.append(w)
        total = sum(weights)
        if total == 100:
            break
        console.print(
            f"  [red]Weights sum to {total}%, not 100%. Try again.[/red]"
        )

    criteria = [
        Criterion(
            name=cd["name"],
            weight=w / 100.0,
            description=cd.get("description", ""),
            is_cost=cd.get("is_cost", False),
        )
        for cd, w in zip(criteria_defs, weights)
    ]
    return criteria, [], None


def _step_pairwise(
    criteria_defs: list[dict],
) -> tuple[list[Criterion], list[PairwiseComparison], float]:
    """AHP pairwise comparison for Standard/Deep tiers."""
    names = [cd["name"] for cd in criteria_defs]
    n = len(names)
    total_comps = required_comparisons(n)

    console.print(f"\n[bold]Step 4: Pairwise Comparisons ({total_comps} pairs)[/bold]")
    console.print("  [dim]For each pair, indicate which is more important and by how much.[/dim]")
    console.print("  [dim]Type 'q' to skip remaining (treated as equal).[/dim]\n")

    comparisons: list[PairwiseComparison] = []
    comp_num = 0
    quit_early = False

    for i in range(n):
        if quit_early:
            break
        for j in range(i + 1, n):
            comp_num += 1
            a_name, b_name = names[i], names[j]

            console.print(
                f"  [bold cyan]({comp_num}/{total_comps})[/bold cyan] "
                f"[bold]{a_name}[/bold] vs [bold]{b_name}[/bold]"
            )
            for idx, (_, label) in enumerate(PAIRWISE_LABELS):
                display = label.format(a=a_name, b=b_name)
                console.print(f"    [{idx + 1}] {display}")

            while True:
                choice = Prompt.ask("    Choice", default="1")
                if choice.lower() == "q":
                    quit_early = True
                    # Fill remaining with 1.0 (equal)
                    comparisons.append(
                        PairwiseComparison(a_name, b_name, 1.0)
                    )
                    break
                try:
                    c = int(choice)
                    if 1 <= c <= 9:
                        saaty_val = PAIRWISE_LABELS[c - 1][0]
                        comparisons.append(
                            PairwiseComparison(a_name, b_name, saaty_val)
                        )
                        break
                except ValueError:
                    pass
                console.print("    [red]Enter 1-9 or 'q'.[/red]")

            if quit_early:
                # Fill all remaining pairs as equal
                for ii in range(i, n):
                    start_j = j + 1 if ii == i else ii + 1
                    for jj in range(start_j, n):
                        comparisons.append(
                            PairwiseComparison(names[ii], names[jj], 1.0)
                        )
                break

    # Compute weights
    matrix = build_comparison_matrix(names, comparisons)
    weights = compute_priority_vector(matrix)
    cr = compute_consistency_ratio(matrix, weights)

    # Show weights
    console.print("\n  [bold]Derived Weights:[/bold]")
    for name, w in zip(names, weights):
        bar = "█" * int(w * 40)
        console.print(f"    {name:<20} {w:>6.1%} {bar}")

    # CR check
    if cr > 0.10:
        console.print(
            f"\n  [yellow]Warning: Consistency Ratio = {cr:.3f} (> 0.10)[/yellow]"
        )
        console.print(
            "  [yellow]Your comparisons contain contradictions.[/yellow]"
        )
        if Confirm.ask("  Redo pairwise comparisons?", default=False):
            return _step_pairwise(criteria_defs)
    else:
        console.print(f"  [green]Consistency Ratio: {cr:.3f} (OK)[/green]")

    criteria = [
        Criterion(
            name=cd["name"],
            weight=w,
            description=cd.get("description", ""),
            is_cost=cd.get("is_cost", False),
        )
        for cd, w in zip(criteria_defs, weights)
    ]
    return criteria, comparisons, cr


def _step_scoring(
    alternatives: list[Alternative],
    criteria: list[Criterion],
) -> list[Score]:
    """Score each alternative on each criterion (1-10)."""
    console.print("\n[bold]Step 5: Rate each option[/bold]")
    console.print("  [dim]Score 1-10 for each criterion (10 = best for benefit, 10 = worst for cost).[/dim]\n")

    scores: list[Score] = []
    for alt in alternatives:
        console.print(f"  [bold]{alt.name}:[/bold]")
        for crit in criteria:
            cost_hint = " (lower=better)" if crit.is_cost else ""
            val = IntPrompt.ask(
                f"    {crit.name}{cost_hint}",
                default=5,
            )
            val = max(1, min(10, val))
            scores.append(Score(alt.name, crit.name, float(val)))
    return scores


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _display_criteria_table(criteria: tuple[Criterion, ...] | list[Criterion]) -> None:
    table = Table(title="Criteria Weights")
    table.add_column("Criterion")
    table.add_column("Weight", justify="right")
    table.add_column("Type")
    table.add_column("Bar")
    for c in sorted(criteria, key=lambda x: x.weight, reverse=True):
        ctype = "[red]Cost[/red]" if c.is_cost else "[green]Benefit[/green]"
        bar = "█" * int(c.weight * 40)
        table.add_row(c.name, f"{c.weight:.1%}", ctype, bar)
    console.print(table)


def _display_ranking_table(
    rankings: dict[str, tuple[RankingResult, ...] | list[RankingResult]],
) -> None:
    for method, results in rankings.items():
        sorted_results = sorted(results, key=lambda r: r.rank)
        table = Table(title=f"Rankings — {method.upper()}")
        table.add_column("#", justify="right", style="bold")
        table.add_column("Alternative")
        table.add_column("Score", justify="right")
        for r in sorted_results:
            style = "bold green" if r.rank == 1 else ""
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(r.rank, "")
            table.add_row(
                str(r.rank),
                f"{medal} {r.alternative_name}" if medal else r.alternative_name,
                f"{r.score:.4f}",
                style=style,
            )
        console.print(table)


def _display_sensitivity(
    sensitivity: tuple[SensitivityResult, ...] | list[SensitivityResult],
) -> None:
    tree = Tree("[bold]Sensitivity Analysis[/bold]")
    for s in sensitivity:
        if s.threshold_pct is None:
            tree.add(
                f"[green]{s.criterion_name}[/green] — "
                f"Stable (rank unchanged within ±50%)"
            )
        else:
            color = "red" if s.threshold_pct < 15 else "yellow" if s.threshold_pct < 30 else "green"
            tree.add(
                f"[{color}]{s.criterion_name}[/{color}] — "
                f"Flips at ±{s.threshold_pct:.0f}% → {s.flip_to}"
            )
    console.print(tree)


def _plotext_show(plt) -> bool:
    """Draw a plotext figure, or report failure so the caller can fall back.

    plotext writes its block-drawing characters straight to sys.stdout rather
    than through Rich. On a Windows console still on a legacy code page that
    raises UnicodeEncodeError, which aborted the wizard *after* the decision
    had already been saved. A chart is never worth losing the results screen.
    """
    try:
        plt.show()
        return True
    except (UnicodeEncodeError, OSError):
        return False


def _try_plotext_ranking(rankings: dict) -> bool:
    """Try to render ranking chart with plotext. Returns False if not available."""
    try:
        import plotext as plt
    except ImportError:
        return False

    plt.clear_figure()
    plt.theme("clear")

    # Use first ranking method
    for method, results in rankings.items():
        sorted_r = sorted(results, key=lambda r: r.rank)
        names = [r.alternative_name for r in sorted_r]
        scores = [r.score for r in sorted_r]
        plt.bar(names, scores, label=method.upper())
        break  # Just show first method in terminal

    plt.title("Rankings")
    return _plotext_show(plt)


def _try_plotext_weights(criteria) -> bool:
    """Try to render criteria weights with plotext."""
    try:
        import plotext as plt
    except ImportError:
        return False

    sorted_c = sorted(criteria, key=lambda c: c.weight, reverse=True)
    names = [c.name for c in sorted_c]
    weights = [c.weight * 100 for c in sorted_c]

    plt.clear_figure()
    plt.theme("clear")
    plt.bar(names, weights)
    plt.title("Criteria Weights (%)")
    return _plotext_show(plt)


def _try_plotext_sensitivity(sensitivity) -> bool:
    """Try to render sensitivity chart with plotext."""
    try:
        import plotext as plt
    except ImportError:
        return False

    names = []
    thresholds = []
    for s in sensitivity:
        names.append(s.criterion_name)
        thresholds.append(s.threshold_pct if s.threshold_pct is not None else 50.0)

    plt.clear_figure()
    plt.theme("clear")
    plt.bar(names, thresholds)
    plt.title("Sensitivity Thresholds (% change to flip)")
    return _plotext_show(plt)


def _format_sensitivity_brief(
    sensitivity: tuple[SensitivityResult, ...],
) -> str:
    lines = []
    for s in sensitivity:
        if s.threshold_pct is None:
            lines.append(f"{s.criterion_name}: stable")
        else:
            lines.append(
                f"{s.criterion_name}: flips at ±{s.threshold_pct:.0f}% → {s.flip_to}"
            )
    return "\n".join(lines)
