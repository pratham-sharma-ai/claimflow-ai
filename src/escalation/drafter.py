"""
Escalation Email Drafter for ClaimFlow AI.

Generates professional escalation emails using case data,
rejection analysis, and relevant precedents.
"""

from datetime import datetime
from typing import Optional

from ..llm.gemini_client import GeminiClient
from ..utils.logger import get_logger

logger = get_logger("claimflow.drafter")


class EscalationDrafter:
    """
    Drafts escalation emails for insurance claim disputes.

    Generates context-aware, professional emails that cite
    relevant precedents and IRDAI guidelines.
    """

    def __init__(self, llm_client: GeminiClient):
        """
        Initialize drafter.

        Args:
            llm_client: Gemini client for generation.
        """
        self.llm_client = llm_client

    def draft(
        self,
        case_data: dict,
        rejection_analysis: dict,
        precedents: list[dict],
        escalation_level: int = 1,
        previous_escalation_dates: list[str] | None = None,
    ) -> str:
        """
        Draft an escalation email.

        Args:
            case_data: Case details dictionary.
            rejection_analysis: Parsed rejection analysis.
            precedents: List of relevant precedent cases.
            escalation_level: Current escalation level (1-3).
            previous_escalation_dates: Dates of previous escalations.

        Returns:
            Complete email text.
        """
        # Use LLM for dynamic generation
        return self.llm_client.draft_escalation(
            case_data=case_data,
            rejection_analysis=rejection_analysis,
            precedents=precedents,
            escalation_level=escalation_level,
        )

    def draft_from_template(
        self,
        case_data: dict,
        rejection_analysis: dict,
        precedents: list[dict],
        escalation_level: int = 1,
    ) -> str:
        """
        Draft using structured template (fallback if LLM unavailable).

        Args:
            case_data: Case details dictionary.
            rejection_analysis: Parsed rejection analysis.
            precedents: List of relevant precedent cases.
            escalation_level: Current escalation level.

        Returns:
            Complete email text.
        """
        claimant = case_data.get("claimant", {})
        claim = case_data.get("claim", {})
        today = datetime.now().strftime("%d %B %Y")

        # Build precedent citations
        precedent_text = ""
        for i, p in enumerate(precedents[:3], 1):
            title = p.get("title", "Insurance Ombudsman Ruling")
            ruling = p.get("key_ruling", p.get("summary", "Ruling in favor of claimant"))
            source = p.get("source_url", "")
            precedent_text += f"""
{i}. {title}
   Ruling: {ruling}
   Source: {source}
"""

        # Select template based on level
        if escalation_level == 1:
            email = self._template_level_1(
                claimant, claim, rejection_analysis, precedent_text, today
            )
        elif escalation_level == 2:
            email = self._template_level_2(
                claimant, claim, rejection_analysis, precedent_text, today
            )
        else:
            email = self._template_level_3(
                claimant, claim, rejection_analysis, precedent_text, today
            )

        return email

    def _template_level_1(
        self,
        claimant: dict,
        claim: dict,
        rejection: dict,
        precedents: str,
        date: str,
    ) -> str:
        """First escalation template."""
        return f"""Subject: Follow-up - Claim #{claimant.get('policy_number', 'N/A')} - Request for Review

Date: {date}

To,
The Grievance Redressal Officer
{claimant.get('insurer', 'Insurance Company')}

Dear Sir/Madam,

I am writing to follow up on my health insurance claim (Policy No: {claimant.get('policy_number', 'N/A')}) which was rejected on {claim.get('rejection_date', 'N/A')}.

CLAIM DETAILS:
- Policyholder: {claimant.get('name', 'N/A')}
- Condition Claimed: {claim.get('condition', 'N/A')}
- Hospitalization Date: {claim.get('hospitalization_date', 'N/A')}
- Claim Amount: {claim.get('claim_amount', 'N/A')}

REJECTION REASON STATED:
{rejection.get('stated_reason', 'Non-disclosure of pre-existing condition')}

MY RESPONSE:
The condition cited in your rejection ({rejection.get('conditions_cited', 'N/A')}) is medically unrelated to the claimed condition ({claim.get('condition', 'N/A')}). I request that your medical team establish a causal link between these conditions before maintaining this rejection.

RELEVANT PRECEDENTS:
{precedents}

As per IRDAI guidelines, rejection on grounds of non-disclosure requires the insurer to establish that:
1. The non-disclosed condition is material to the claim
2. There is a causal relationship between the conditions

I request:
1. A detailed medical causality analysis
2. Review by your medical board
3. Written explanation citing specific policy clauses

Please respond within 15 working days as per IRDAI grievance redressal timelines.

Regards,
{claimant.get('name', 'Policyholder')}
Contact: {claimant.get('email', '')}
"""

    def _template_level_2(
        self,
        claimant: dict,
        claim: dict,
        rejection: dict,
        precedents: str,
        date: str,
    ) -> str:
        """Second escalation - senior review request."""
        return f"""Subject: ESCALATION - Claim #{claimant.get('policy_number', 'N/A')} - Senior Review Requested

Date: {date}

To,
The Head - Claims & Grievance Redressal
{claimant.get('insurer', 'Insurance Company')}

CC: Compliance Officer

Dear Sir/Madam,

This is my second escalation regarding claim rejection for Policy No: {claimant.get('policy_number', 'N/A')}.

Despite my previous correspondence, I have received only templated responses that do not address the substantive issues raised. This indicates a failure in your grievance redressal process.

SUMMARY OF ISSUE:
- My claim for {claim.get('condition', 'N/A')} was rejected citing non-disclosure
- The cited condition is medically unrelated to the claim
- No causal link has been established by your team
- My requests for medical board review have been ignored

REGULATORY CONTEXT:
Per IRDAI (Protection of Policyholders' Interests) Regulations, insurers must:
- Provide specific, reasoned rejections
- Establish material connection for non-disclosure rejections
- Complete grievance redressal within 30 days

PRECEDENTS SUPPORTING MY POSITION:
{precedents}

I REQUEST:
1. Immediate escalation to your senior claims committee
2. Review by your compliance/legal team
3. Written response addressing each point raised
4. If rejection is maintained, provide detailed medical causality report

If I do not receive a substantive response within 10 working days, I will be compelled to:
- File a complaint with IRDAI IGMS
- Approach the Insurance Ombudsman
- Consider legal remedies

This is not a threat but a statement of my rights as a policyholder.

Regards,
{claimant.get('name', 'Policyholder')}
Policy No: {claimant.get('policy_number', 'N/A')}
"""

    def _template_level_3(
        self,
        claimant: dict,
        claim: dict,
        rejection: dict,
        precedents: str,
        date: str,
    ) -> str:
        """Third escalation - pre-legal notice."""
        return f"""Subject: FINAL NOTICE - Claim #{claimant.get('policy_number', 'N/A')} - Pre-Legal

Date: {date}

To,
The Managing Director / CEO
{claimant.get('insurer', 'Insurance Company')}

CC:
- Chief Compliance Officer
- Head of Legal
- IRDAI (for records)

NOTICE UNDER CONSUMER PROTECTION ACT, 2019

Dear Sir/Madam,

This serves as a final notice before I initiate formal legal and regulatory action regarding the wrongful rejection of my health insurance claim.

CLAIM REFERENCE: Policy No. {claimant.get('policy_number', 'N/A')}
CLAIMED CONDITION: {claim.get('condition', 'N/A')}
CLAIM AMOUNT: {claim.get('claim_amount', 'N/A')}

CHRONOLOGY OF GRIEVANCE:
1. Claim rejected on grounds of non-disclosure
2. Multiple escalations sent with no substantive response
3. Relevant IRDAI guidelines and Ombudsman precedents cited
4. No medical causality analysis provided
5. Templated responses received repeatedly

LEGAL POSITION:
Your rejection is legally unsustainable because:
1. No causal link established between disclosed and claimed conditions
2. Insurance Ombudsman precedents clearly support my position (see: {precedents[:200]}...)
3. Your grievance process has failed to provide reasoned responses
4. This constitutes deficiency in service under Consumer Protection Act

DEMAND:
1. Immediate settlement of claim with applicable interest
2. Compensation for mental harassment and deficiency in service
3. Written apology for process failures

TIMELINE: 7 days from receipt of this notice

CONSEQUENCES OF NON-COMPLIANCE:
- Complaint to IRDAI IGMS
- Complaint to Insurance Ombudsman
- Consumer Court proceedings
- Public disclosure of unfair trade practices

I reserve all rights under law.

{claimant.get('name', 'Policyholder')}
Policy No: {claimant.get('policy_number', 'N/A')}
Date: {date}
"""

    def draft_linkedin_post(
        self,
        case_data: dict,
        days_unresolved: int,
        escalation_count: int,
    ) -> str:
        """
        Draft a LinkedIn post for public accountability.

        Args:
            case_data: Case details.
            days_unresolved: Days since initial rejection.
            escalation_count: Number of escalations sent.

        Returns:
            LinkedIn post draft.
        """
        prompt = f"""Draft a professional LinkedIn post about an unresolved insurance claim.

CONTEXT:
- Days unresolved: {days_unresolved}
- Escalations sent: {escalation_count}
- Insurer: {case_data.get('claimant', {}).get('insurer', 'N/A')}
- Issue: Claim rejected for unrelated pre-existing condition

REQUIREMENTS:
1. Professional, not emotional
2. Focus on systemic issues, not personal attack
3. Include relevant hashtags
4. Invite industry discussion
5. Mention building a solution (ClaimFlow AI)
6. Keep under 1500 characters

Draft the post:"""

        return self.llm_client.generate(
            prompt=prompt,
            model=self.llm_client.MODELS["balanced"],
            temperature=0.5,
        )
