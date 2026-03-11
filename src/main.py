"""
ClaimFlow AI - Main CLI Entry Point

A dual-sided agentic system for insurance claim resolution.
"""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .llm.gemini_client import GeminiClient
from .knowledge.scraper import PrecedentScraper
from .knowledge.vector_store import VectorStore
from .intake.case_builder import CaseBuilder, Case
from .analyzer.rejection_parser import RejectionParser
from .analyzer.precedent_matcher import PrecedentMatcher
from .escalation.email_client import YahooEmailClient
from .escalation.drafter import EscalationDrafter
from .escalation.response_detector import ResponseDetector
from .utils.config import load_config
from .utils.logger import setup_logger

app = typer.Typer(
    name="claimflow",
    help="ClaimFlow AI - Insurance Claim Resolution System",
    add_completion=False,
)
console = Console()


def get_clients(config: dict) -> tuple[GeminiClient, VectorStore]:
    """Initialize LLM and vector store clients."""
    llm = GeminiClient(
        api_key=config.get("gemini_api_key"),
        default_model=config.get("gemini_model", "gemini-2.5-flash"),
    )
    vector_store = VectorStore(llm_client=llm)
    return llm, vector_store


@app.command()
def init():
    """Initialize ClaimFlow AI and verify configuration."""
    console.print(Panel.fit(
        "[bold blue]ClaimFlow AI[/bold blue]\n"
        "Dual-sided Insurance Claim Resolution System",
        border_style="blue"
    ))

    config = load_config()

    # Check configuration
    checks = []

    if config.get("gemini_api_key"):
        checks.append(("[green]✓[/green]", "Gemini API Key", "Configured"))
    else:
        checks.append(("[red]✗[/red]", "Gemini API Key", "Missing - set GEMINI_API_KEY"))

    if config.get("yahoo_email") and config.get("yahoo_app_password"):
        checks.append(("[green]✓[/green]", "Yahoo Email", "Configured"))
    else:
        checks.append(("[yellow]![/yellow]", "Yahoo Email", "Optional - set YAHOO_EMAIL and YAHOO_APP_PASSWORD"))

    table = Table(title="Configuration Status")
    table.add_column("Status")
    table.add_column("Component")
    table.add_column("Details")

    for check in checks:
        table.add_row(*check)

    console.print(table)

    # Test Gemini connection
    if config.get("gemini_api_key"):
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            progress.add_task("Testing Gemini connection...", total=None)
            try:
                llm = GeminiClient(api_key=config["gemini_api_key"])
                response = llm.generate("Say 'ClaimFlow AI initialized' in one line.")
                console.print(f"\n[green]Gemini Response:[/green] {response.strip()}")
                llm.close()
            except Exception as e:
                console.print(f"\n[red]Gemini Error:[/red] {e}")


@app.command()
def new_case():
    """Create a new case interactively."""
    builder = CaseBuilder()
    case = builder.build_interactive()
    console.print(f"\n[green]Case {case.id} created successfully![/green]")


@app.command()
def list_cases():
    """List all saved cases."""
    builder = CaseBuilder()
    cases = builder.list_cases()

    if not cases:
        console.print("[yellow]No cases found. Use 'claimflow new-case' to create one.[/yellow]")
        return

    table = Table(title="Saved Cases")
    table.add_column("Case ID")
    table.add_column("Claimant")
    table.add_column("Insurer")
    table.add_column("Status")

    for case in cases:
        table.add_row(
            case["id"],
            case["claimant"],
            case["insurer"],
            case["status"],
        )

    console.print(table)


@app.command()
def view_case(case_id: str):
    """View details of a specific case."""
    builder = CaseBuilder()
    case = builder.load_case(case_id)

    if not case:
        console.print(f"[red]Case {case_id} not found.[/red]")
        raise typer.Exit(1)

    builder.display_case(case)


@app.command()
def scrape(
    source: str = typer.Option("all", help="Source to scrape (livemint, economictimes, all)"),
    max_articles: int = typer.Option(20, help="Maximum articles per source"),
):
    """Scrape precedents from news sources."""
    config = load_config()

    if not config.get("gemini_api_key"):
        console.print("[red]Gemini API key required for scraping. Set GEMINI_API_KEY.[/red]")
        raise typer.Exit(1)

    async def run_scrape():
        llm = GeminiClient(api_key=config["gemini_api_key"])
        vector_store = VectorStore(llm_client=llm)

        async with PrecedentScraper(llm_client=llm) as scraper:
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
                if source == "all":
                    task = progress.add_task("Scraping all sources...", total=None)
                    precedents = await scraper.scrape_all(max_per_source=max_articles)
                else:
                    task = progress.add_task(f"Scraping {source}...", total=None)
                    precedents = await scraper.scrape_source(source, max_articles=max_articles)

            console.print(f"\n[green]Scraped {len(precedents)} precedents[/green]")

            # Add to vector store
            if precedents:
                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
                    progress.add_task("Adding to vector store...", total=None)
                    added = vector_store.add_precedents(precedents)
                    console.print(f"[green]Added {added} to vector store (total: {vector_store.count()})[/green]")

        llm.close()

    asyncio.run(run_scrape())


@app.command()
def analyze(
    case_id: str,
    rejection_email: str = typer.Option(None, help="Path to rejection email file"),
):
    """Analyze a rejection and find precedents."""
    config = load_config()
    builder = CaseBuilder()
    case = builder.load_case(case_id)

    if not case:
        console.print(f"[red]Case {case_id} not found.[/red]")
        raise typer.Exit(1)

    llm, vector_store = get_clients(config)

    # Get rejection text
    if rejection_email:
        rejection_text = Path(rejection_email).read_text()
    else:
        rejection_text = case.rejection.stated_reason

    # Parse rejection
    parser = RejectionParser(llm_client=llm)
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        progress.add_task("Analyzing rejection...", total=None)
        parsed = parser.parse(rejection_text, case.to_dict())

    console.print("\n[bold]Rejection Analysis:[/bold]")
    console.print(f"  Type: {parsed.rejection_type}")
    console.print(f"  Reason: {parsed.stated_reason}")
    console.print(f"  Conditions Cited: {', '.join(parsed.conditions_cited) or 'None'}")
    console.print(f"  Causality Established: {parsed.causality_established}")
    console.print(f"  Weak Points: {', '.join(parsed.weak_points) or 'None identified'}")

    # Find precedents
    if vector_store.count() > 0:
        matcher = PrecedentMatcher(vector_store)
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            progress.add_task("Finding precedents...", total=None)
            matches = matcher.find_for_rejection(parsed, case.to_dict())

        if matches:
            console.print("\n[bold]Relevant Precedents:[/bold]")
            for i, m in enumerate(matches[:3], 1):
                console.print(f"\n  {i}. {m.title}")
                console.print(f"     Ruling: {m.key_ruling}")
                console.print(f"     Relevance: {m.applicable_reason}")
                console.print(f"     Score: {m.relevance_score:.2f}")
    else:
        console.print("\n[yellow]No precedents in database. Run 'claimflow scrape' first.[/yellow]")

    llm.close()


@app.command()
def draft(
    case_id: str,
    level: int = typer.Option(1, help="Escalation level (1-3)"),
    output: str = typer.Option(None, help="Output file path"),
):
    """Draft an escalation email for a case."""
    config = load_config()
    builder = CaseBuilder()
    case = builder.load_case(case_id)

    if not case:
        console.print(f"[red]Case {case_id} not found.[/red]")
        raise typer.Exit(1)

    llm, vector_store = get_clients(config)

    # Get precedents
    precedents = []
    if vector_store.count() > 0:
        matcher = PrecedentMatcher(vector_store)
        parser = RejectionParser(llm_client=llm)
        parsed = parser.parse(case.rejection.stated_reason, case.to_dict())
        matches = matcher.find_for_rejection(parsed, case.to_dict())
        precedents = [{"title": m.title, "key_ruling": m.key_ruling, "source_url": m.source_url} for m in matches]

    # Draft email
    drafter = EscalationDrafter(llm_client=llm)

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        progress.add_task("Drafting escalation email...", total=None)

        rejection_analysis = {
            "rejection_type": "non_disclosure",
            "stated_reason": case.rejection.stated_reason,
            "conditions_cited": case.rejection.condition_cited,
            "weak_points": ["No causal link established"],
        }

        email_text = drafter.draft(
            case_data=case.to_dict(),
            rejection_analysis=rejection_analysis,
            precedents=precedents,
            escalation_level=level,
        )

    console.print(Panel(email_text, title=f"Escalation Level {level} Draft", border_style="green"))

    if output:
        Path(output).write_text(email_text)
        console.print(f"\n[green]Saved to {output}[/green]")

    llm.close()


@app.command()
def send(
    case_id: str,
    to: str,
    level: int = typer.Option(1, help="Escalation level"),
    draft_file: str = typer.Option(None, help="Path to draft file (optional)"),
):
    """Send an escalation email."""
    config = load_config()

    if not config.get("yahoo_email") or not config.get("yahoo_app_password"):
        console.print("[red]Yahoo email not configured. Set YAHOO_EMAIL and YAHOO_APP_PASSWORD.[/red]")
        raise typer.Exit(1)

    builder = CaseBuilder()
    case = builder.load_case(case_id)

    if not case:
        console.print(f"[red]Case {case_id} not found.[/red]")
        raise typer.Exit(1)

    # Get email content
    if draft_file:
        body = Path(draft_file).read_text()
    else:
        # Generate draft
        llm, vector_store = get_clients(config)
        drafter = EscalationDrafter(llm_client=llm)

        rejection_analysis = {
            "rejection_type": "non_disclosure",
            "stated_reason": case.rejection.stated_reason,
        }

        body = drafter.draft_from_template(
            case_data=case.to_dict(),
            rejection_analysis=rejection_analysis,
            precedents=[],
            escalation_level=level,
        )
        llm.close()

    # Send email
    with YahooEmailClient() as email_client:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            progress.add_task("Sending email...", total=None)

            message_id = email_client.send_escalation(
                to=to,
                claim_id=case.claimant.policy_number,
                escalation_level=level,
                body=body,
            )

    console.print(f"\n[green]Email sent successfully![/green]")
    console.print(f"Message ID: {message_id}")

    # Update case
    from datetime import datetime
    case.add_escalation(level, message_id, datetime.now().isoformat())
    builder.save_case(case)


@app.command()
def check_replies(case_id: str):
    """Check for replies to escalation emails."""
    config = load_config()

    if not config.get("yahoo_email"):
        console.print("[red]Yahoo email not configured.[/red]")
        raise typer.Exit(1)

    builder = CaseBuilder()
    case = builder.load_case(case_id)

    if not case:
        console.print(f"[red]Case {case_id} not found.[/red]")
        raise typer.Exit(1)

    llm = GeminiClient(api_key=config["gemini_api_key"]) if config.get("gemini_api_key") else None
    detector = ResponseDetector(llm_client=llm)

    with YahooEmailClient() as email_client:
        # Search for replies from insurer
        insurer = case.claimant.insurer.lower()
        emails = email_client.search_by_subject(case.claimant.policy_number, limit=20)

        if not emails:
            console.print("[yellow]No replies found.[/yellow]")
            return

        console.print(f"\n[bold]Found {len(emails)} related emails:[/bold]\n")

        for email in emails:
            console.print(f"From: {email.from_addr}")
            console.print(f"Date: {email.date}")
            console.print(f"Subject: {email.subject}")

            # Analyze response
            analysis = detector.analyze(email.body)
            console.print(f"Template Detected: {analysis.is_templated}")
            console.print(f"Recommendation: {analysis.recommendation}")
            console.print(f"Explanation: {analysis.explanation}")
            console.print("-" * 50)

    if llm:
        llm.close()


@app.command()
def stats():
    """Show system statistics."""
    config = load_config()

    table = Table(title="ClaimFlow AI Statistics")
    table.add_column("Metric")
    table.add_column("Value")

    # Count cases
    builder = CaseBuilder()
    cases = builder.list_cases()
    table.add_row("Total Cases", str(len(cases)))

    # Count by status
    status_counts = {}
    for case in cases:
        status = case.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    for status, count in status_counts.items():
        table.add_row(f"  - {status}", str(count))

    # Vector store count
    if config.get("gemini_api_key"):
        try:
            llm = GeminiClient(api_key=config["gemini_api_key"])
            vs = VectorStore(llm_client=llm)
            table.add_row("Precedents in DB", str(vs.count()))
            llm.close()
        except Exception:
            table.add_row("Precedents in DB", "Error")
    else:
        table.add_row("Precedents in DB", "N/A (no API key)")

    console.print(table)


def main():
    """Main entry point."""
    setup_logger()
    app()


if __name__ == "__main__":
    main()
