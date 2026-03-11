"""
Case Builder for ClaimFlow AI.

Interactive module to collect and structure case information
from claimants.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.table import Table

from ..utils.logger import get_logger
from ..utils.config import get_project_root

logger = get_logger("claimflow.intake")
console = Console()


@dataclass
class Claimant:
    """Claimant information."""
    name: str
    email: str
    phone: Optional[str] = None
    policy_number: str = ""
    insurer: str = ""
    intermediary: Optional[str] = None  # e.g., Policybazaar


@dataclass
class Claim:
    """Claim details."""
    condition: str  # e.g., Stroke (CVA)
    hospitalization_date: str
    discharge_date: Optional[str] = None
    claim_amount: str = ""
    claim_date: str = ""
    hospital_name: Optional[str] = None


@dataclass
class Rejection:
    """Rejection details."""
    date: str
    stated_reason: str
    condition_cited: Optional[str] = None  # Pre-existing condition cited
    clauses_cited: list[str] = field(default_factory=list)
    documents_requested: list[str] = field(default_factory=list)


@dataclass
class TimelineEvent:
    """Single event in claim timeline."""
    date: str
    action: str
    by: str  # "claimant" or "insurer"
    response: Optional[str] = None
    evidence: Optional[str] = None  # Path to evidence file


@dataclass
class Case:
    """Complete case representation."""
    id: str
    claimant: Claimant
    claim: Claim
    rejection: Rejection
    timeline: list[TimelineEvent] = field(default_factory=list)
    escalation_history: list[dict] = field(default_factory=list)
    status: str = "rejected"  # rejected, escalating, resolved
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "claimant": asdict(self.claimant),
            "claim": asdict(self.claim),
            "rejection": asdict(self.rejection),
            "timeline": [asdict(e) for e in self.timeline],
            "escalation_history": self.escalation_history,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Case":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            claimant=Claimant(**data["claimant"]),
            claim=Claim(**data["claim"]),
            rejection=Rejection(**data["rejection"]),
            timeline=[TimelineEvent(**e) for e in data.get("timeline", [])],
            escalation_history=data.get("escalation_history", []),
            status=data.get("status", "rejected"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def add_escalation(self, level: int, email_id: str, date: str) -> None:
        """Record an escalation."""
        self.escalation_history.append({
            "level": level,
            "email_id": email_id,
            "date": date,
            "response_received": False,
        })
        self.status = "escalating"
        self.updated_at = datetime.now().isoformat()

    def get_escalation_level(self) -> int:
        """Get current escalation level."""
        return len(self.escalation_history) + 1


class CaseBuilder:
    """
    Builds case files through interactive prompts or direct input.
    """

    def __init__(self, cases_dir: Path | None = None):
        """
        Initialize case builder.

        Args:
            cases_dir: Directory to store case files.
        """
        self.cases_dir = cases_dir or get_project_root() / "data" / "cases"
        self.cases_dir.mkdir(parents=True, exist_ok=True)

    def build_interactive(self) -> Case:
        """
        Build a case through interactive CLI prompts.

        Returns:
            Constructed Case object.
        """
        console.print(Panel.fit(
            "[bold blue]ClaimFlow AI - Case Builder[/bold blue]\n"
            "Let's gather information about your insurance claim.",
            border_style="blue"
        ))

        # Claimant info
        console.print("\n[bold]1. Your Information[/bold]")
        name = Prompt.ask("Your full name")
        email = Prompt.ask("Email address")
        phone = Prompt.ask("Phone number (optional)", default="")
        policy_number = Prompt.ask("Policy number")
        insurer = Prompt.ask("Insurance company name")
        intermediary = Prompt.ask("Intermediary (e.g., Policybazaar)", default="")

        claimant = Claimant(
            name=name,
            email=email,
            phone=phone or None,
            policy_number=policy_number,
            insurer=insurer,
            intermediary=intermediary or None,
        )

        # Claim info
        console.print("\n[bold]2. Claim Details[/bold]")
        condition = Prompt.ask("Medical condition claimed (e.g., Stroke, Heart Attack)")
        hospitalization_date = Prompt.ask("Hospitalization date (DD-MM-YYYY)")
        discharge_date = Prompt.ask("Discharge date (DD-MM-YYYY)", default="")
        claim_amount = Prompt.ask("Claim amount (INR)")
        claim_date = Prompt.ask("Claim submission date (DD-MM-YYYY)")
        hospital_name = Prompt.ask("Hospital name", default="")

        claim = Claim(
            condition=condition,
            hospitalization_date=hospitalization_date,
            discharge_date=discharge_date or None,
            claim_amount=claim_amount,
            claim_date=claim_date,
            hospital_name=hospital_name or None,
        )

        # Rejection info
        console.print("\n[bold]3. Rejection Details[/bold]")
        rejection_date = Prompt.ask("Rejection date (DD-MM-YYYY)")
        stated_reason = Prompt.ask("Reason stated by insurer for rejection")
        condition_cited = Prompt.ask(
            "Pre-existing condition cited (if any)",
            default=""
        )

        console.print("Any policy clauses cited? (comma-separated, or press Enter to skip)")
        clauses_input = Prompt.ask("Clauses", default="")
        clauses = [c.strip() for c in clauses_input.split(",") if c.strip()]

        rejection = Rejection(
            date=rejection_date,
            stated_reason=stated_reason,
            condition_cited=condition_cited or None,
            clauses_cited=clauses,
        )

        # Generate case ID
        case_id = f"CASE_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        case = Case(
            id=case_id,
            claimant=claimant,
            claim=claim,
            rejection=rejection,
        )

        # Add timeline
        if Confirm.ask("\nWould you like to add timeline events?"):
            self._add_timeline_interactive(case)

        # Save case
        self.save_case(case)

        console.print(Panel.fit(
            f"[green]Case created successfully![/green]\n"
            f"Case ID: [bold]{case_id}[/bold]\n"
            f"Saved to: {self.cases_dir / f'{case_id}.json'}",
            border_style="green"
        ))

        return case

    def _add_timeline_interactive(self, case: Case) -> None:
        """Add timeline events interactively."""
        console.print("\n[bold]Timeline Events[/bold]")
        console.print("Add events in chronological order. Type 'done' when finished.\n")

        while True:
            date = Prompt.ask("Event date (DD-MM-YYYY) or 'done'")
            if date.lower() == "done":
                break

            action = Prompt.ask("What happened?")
            by = Prompt.ask("Action by", choices=["claimant", "insurer"])
            response = Prompt.ask("Response received (if any)", default="")
            evidence = Prompt.ask("Evidence file path (if any)", default="")

            case.timeline.append(TimelineEvent(
                date=date,
                action=action,
                by=by,
                response=response or None,
                evidence=evidence or None,
            ))

    def build_from_dict(self, data: dict) -> Case:
        """
        Build case from a dictionary.

        Args:
            data: Case data dictionary.

        Returns:
            Case object.
        """
        case = Case.from_dict(data)
        self.save_case(case)
        return case

    def save_case(self, case: Case) -> Path:
        """
        Save case to JSON file.

        Args:
            case: Case to save.

        Returns:
            Path to saved file.
        """
        case.updated_at = datetime.now().isoformat()
        filepath = self.cases_dir / f"{case.id}.json"
        filepath.write_text(json.dumps(case.to_dict(), indent=2, ensure_ascii=False))
        logger.info(f"Case saved: {filepath}")
        return filepath

    def load_case(self, case_id: str) -> Case | None:
        """
        Load a case by ID.

        Args:
            case_id: Case identifier.

        Returns:
            Case object or None if not found.
        """
        filepath = self.cases_dir / f"{case_id}.json"
        if not filepath.exists():
            logger.warning(f"Case not found: {case_id}")
            return None

        data = json.loads(filepath.read_text())
        return Case.from_dict(data)

    def list_cases(self) -> list[dict]:
        """List all saved cases."""
        cases = []
        for file in self.cases_dir.glob("*.json"):
            try:
                data = json.loads(file.read_text())
                cases.append({
                    "id": data["id"],
                    "claimant": data["claimant"]["name"],
                    "insurer": data["claimant"]["insurer"],
                    "status": data.get("status", "unknown"),
                    "created_at": data.get("created_at", ""),
                })
            except Exception as e:
                logger.warning(f"Failed to load {file}: {e}")
        return cases

    def display_case(self, case: Case) -> None:
        """Display case details in a formatted table."""
        table = Table(title=f"Case: {case.id}", show_header=True)
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="white")

        # Claimant info
        table.add_row("Name", case.claimant.name)
        table.add_row("Policy #", case.claimant.policy_number)
        table.add_row("Insurer", case.claimant.insurer)

        # Claim info
        table.add_row("Condition", case.claim.condition)
        table.add_row("Claim Amount", case.claim.claim_amount)
        table.add_row("Hospitalization", case.claim.hospitalization_date)

        # Rejection info
        table.add_row("Rejection Date", case.rejection.date)
        table.add_row("Reason", case.rejection.stated_reason)
        if case.rejection.condition_cited:
            table.add_row("Condition Cited", case.rejection.condition_cited)

        # Status
        table.add_row("Status", case.status)
        table.add_row("Escalation Level", str(case.get_escalation_level() - 1))

        console.print(table)
