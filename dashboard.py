"""
ClaimFlow AI - Dashboard

Web-based visualization of insurance claim email analysis.
Shows repetition patterns, timelines, and key findings.

Run: streamlit run dashboard.py
"""

import os
import json
from pathlib import Path
from datetime import datetime

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from dotenv import load_dotenv

# Load .env from project root (local dev)
load_dotenv(Path(__file__).parent / ".env")

# Also load Streamlit Cloud secrets into env vars (for deployed app)
if hasattr(st, "secrets"):
    for key in ["GEMINI_API_KEY", "YAHOO_EMAIL", "YAHOO_APP_PASSWORD"]:
        if key in st.secrets:
            os.environ[key] = st.secrets[key]

from src.escalation.email_client import YahooEmailClient, Email
from src.analyzer.email_analyzer import EmailAnalyzer, AnalysisResult
from src.utils.config import load_config

# ──────────────────────────────────────────────
# Page Configuration
# ──────────────────────────────────────────────

st.set_page_config(
    page_title="ClaimFlow AI",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-radius: 12px;
        padding: 24px;
        text-align: center;
        border: 1px solid #2a2a4a;
    }
    .metric-value {
        font-size: 48px;
        font-weight: 800;
        color: #e94560;
        line-height: 1;
    }
    .metric-label {
        font-size: 14px;
        color: #8892b0;
        margin-top: 8px;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .finding-card {
        background: #0a192f;
        border-left: 4px solid #e94560;
        padding: 16px;
        margin: 8px 0;
        border-radius: 0 8px 8px 0;
    }
    .stApp {
        background-color: #0a0a1a;
    }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────
# Session State
# ──────────────────────────────────────────────

if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None
if "connected" not in st.session_state:
    st.session_state.connected = False
if "emails_fetched" not in st.session_state:
    st.session_state.emails_fetched = False


# ──────────────────────────────────────────────
# Helper Functions (defined before sidebar uses them)
# ──────────────────────────────────────────────

def _save_analysis(result: AnalysisResult) -> None:
    """Save analysis result to JSON."""
    save_dir = Path("data/analysis")
    save_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"analysis_{result.insurer_name.replace(' ', '_')}_{timestamp}.json"

    data = {
        "insurer_name": result.insurer_name,
        "total_emails_received": result.total_emails_received,
        "total_emails_sent": result.total_emails_sent,
        "unique_responses": result.unique_responses,
        "repeated_responses": result.repeated_responses,
        "repetition_rate": result.repetition_rate,
        "avg_response_time_hours": result.avg_response_time_hours,
        "max_response_gap_days": result.max_response_gap_days,
        "template_phrases_found": result.template_phrases_found,
        "first_email_date": result.first_email_date,
        "last_email_date": result.last_email_date,
        "total_days_elapsed": result.total_days_elapsed,
        "key_findings": result.key_findings,
        "timeline": [
            {
                "date": t.date,
                "direction": t.direction,
                "subject": t.subject,
                "body_preview": t.body_preview,
                "is_templated": t.is_templated,
                "response_time_hours": t.response_time_hours,
            }
            for t in result.timeline
        ],
        "email_groups": [
            {
                "count": g.count,
                "subject": g.representative_subject,
                "body_preview": g.representative_body_preview,
                "first_seen": g.first_seen,
                "last_seen": g.last_seen,
            }
            for g in result.email_groups
        ],
    }

    (save_dir / filename).write_text(json.dumps(data, indent=2))


def _load_analysis(filepath: Path) -> AnalysisResult | None:
    """Load analysis from JSON (returns simplified result for display)."""
    try:
        data = json.loads(filepath.read_text())
        return data
    except Exception as e:
        st.error(f"Failed to load: {e}")
        return None


def _generate_demo_data() -> dict:
    """Generate demo data for testing the dashboard."""
    return {
        "insurer_name": "Aditya Birla Health Insurance",
        "total_emails_received": 8,
        "total_emails_sent": 13,
        "unique_responses": 2,
        "repeated_responses": 6,
        "repetition_rate": 0.75,
        "avg_response_time_hours": 120,
        "max_response_gap_days": 14,
        "total_days_elapsed": 90,
        "first_email_date": "2025-12-15T10:00:00Z",
        "last_email_date": "2026-03-01T10:00:00Z",
        "key_findings": [
            "75% of responses are duplicates. Out of 8 emails received, only 2 contained unique content.",
            'The phrase "we regret to inform" appeared in 6 emails, indicating automated responses.',
            "The most repeated response was sent 6 times between 2025-12-25 and 2026-02-28.",
            "Average insurer response time: 5 days.",
            "Issue has been open for 90 days with no resolution.",
            "Every response from the insurer follows the same template. No case-specific medical or legal review has been conducted.",
        ],
        "template_phrases_found": {
            "we regret to inform": 6,
            "as per our records": 5,
            "the claim stands rejected": 6,
            "please refer to the policy terms": 4,
            "our decision remains unchanged": 3,
            "thank you for your patience": 5,
        },
        "timeline": [
            {"date": "2025-12-15T10:00:00Z", "direction": "outgoing", "subject": "Claim Submission - Policy ABHI-XXXXX", "body_preview": "Please find attached all documents for hospitalization claim...", "is_templated": False, "response_time_hours": None},
            {"date": "2025-12-18T14:00:00Z", "direction": "incoming", "subject": "RE: Claim Submission", "body_preview": "Additional documents required...", "is_templated": True, "response_time_hours": 76},
            {"date": "2025-12-20T09:00:00Z", "direction": "outgoing", "subject": "RE: Clarification - No further documents exist", "body_preview": "The requested documents do not exist as no prior treatment...", "is_templated": False, "response_time_hours": 43},
            {"date": "2025-12-25T11:00:00Z", "direction": "incoming", "subject": "Claim Rejection - Non-disclosure", "body_preview": "We regret to inform you that your claim has been rejected due to non-disclosure of pre-existing condition...", "is_templated": True, "response_time_hours": 122},
            {"date": "2025-12-28T08:00:00Z", "direction": "outgoing", "subject": "RE: Appeal - Condition is unrelated", "body_preview": "The cited condition (hypertension) is medically unrelated to stroke...", "is_templated": False, "response_time_hours": 69},
            {"date": "2026-01-05T16:00:00Z", "direction": "incoming", "subject": "RE: Your Claim", "body_preview": "We regret to inform you that your claim stands rejected as per our records...", "is_templated": True, "response_time_hours": 200},
            {"date": "2026-01-08T10:00:00Z", "direction": "outgoing", "subject": "RE: IRDAI Ombudsman Precedent Shared", "body_preview": "Please refer to attached Ombudsman ruling where unrelated conditions...", "is_templated": False, "response_time_hours": 66},
            {"date": "2026-01-10T10:00:00Z", "direction": "outgoing", "subject": "Escalation to Policybazaar", "body_preview": "Reaching out via intermediary for resolution...", "is_templated": False, "response_time_hours": None},
            {"date": "2026-01-18T13:00:00Z", "direction": "incoming", "subject": "RE: Your Claim Status", "body_preview": "We regret to inform you that after careful consideration, our decision remains unchanged...", "is_templated": True, "response_time_hours": 243},
            {"date": "2026-01-20T09:00:00Z", "direction": "outgoing", "subject": "RE: Request for Senior Review", "body_preview": "Requesting escalation to senior claims committee...", "is_templated": False, "response_time_hours": 44},
            {"date": "2026-01-22T09:00:00Z", "direction": "outgoing", "subject": "LinkedIn Post - Systemic Issue", "body_preview": "Posted public reflection on LinkedIn highlighting process gaps...", "is_templated": False, "response_time_hours": None},
            {"date": "2026-01-30T15:00:00Z", "direction": "incoming", "subject": "RE: Claim Reference", "body_preview": "We regret to inform you that the claim stands rejected. Please refer to the policy terms...", "is_templated": True, "response_time_hours": 246},
            {"date": "2026-02-05T10:00:00Z", "direction": "outgoing", "subject": "RE: Final escalation with precedents", "body_preview": "Citing 3 Ombudsman rulings, requesting written causality analysis...", "is_templated": False, "response_time_hours": 139},
            {"date": "2026-02-10T12:00:00Z", "direction": "incoming", "subject": "RE: Your Claim", "body_preview": "As per our records, we regret to inform you that our decision remains unchanged...", "is_templated": True, "response_time_hours": 122},
            {"date": "2026-02-15T10:00:00Z", "direction": "outgoing", "subject": "RE: Requesting compliance review", "body_preview": "Requesting review by compliance/legal team as required by IRDAI...", "is_templated": False, "response_time_hours": 118},
            {"date": "2026-02-20T10:00:00Z", "direction": "outgoing", "subject": "RE: Second LinkedIn Update", "body_preview": "Updated LinkedIn with data analysis of communication pattern...", "is_templated": False, "response_time_hours": None},
            {"date": "2026-02-28T14:00:00Z", "direction": "incoming", "subject": "RE: Grievance", "body_preview": "We regret to inform you that as per our records, the claim stands rejected...", "is_templated": True, "response_time_hours": 316},
            {"date": "2026-03-01T10:00:00Z", "direction": "incoming", "subject": "RE: Claim Update", "body_preview": "Thank you for your patience. As mentioned in our previous communication, we are unable to process...", "is_templated": True, "response_time_hours": 20},
        ],
        "email_groups": [
            {"count": 6, "subject": "RE: Your Claim", "body_preview": "We regret to inform you that your claim stands rejected as per our records. Our decision remains unchanged. Please refer to the policy terms and conditions...", "first_seen": "2025-12-25T11:00:00Z", "last_seen": "2026-02-28T14:00:00Z"},
            {"count": 1, "subject": "RE: Claim Submission", "body_preview": "Additional documents required for processing your claim...", "first_seen": "2025-12-18T14:00:00Z", "last_seen": "2025-12-18T14:00:00Z"},
            {"count": 1, "subject": "RE: Claim Update", "body_preview": "Thank you for your patience. As mentioned in our previous communication...", "first_seen": "2026-03-01T10:00:00Z", "last_seen": "2026-03-01T10:00:00Z"},
        ],
    }


def _get_value(result, key, default=None):
    """Get value from either AnalysisResult or dict."""
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


# ──────────────────────────────────────────────
# Sidebar - Connection & Configuration
# ──────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ Configuration")

    st.divider()

    # Connection mode
    mode = st.radio(
        "Data Source",
        ["Connect to Yahoo Mail", "Load from saved analysis"],
        index=0,
    )

    if mode == "Connect to Yahoo Mail":
        st.subheader("Yahoo Mail Connection")

        # Pre-fill from .env if available
        env_email = os.getenv("YAHOO_EMAIL", "")
        env_password = os.getenv("YAHOO_APP_PASSWORD", "")

        yahoo_email = st.text_input(
            "Yahoo Email Address",
            value=env_email,
            help="Set YAHOO_EMAIL in .env or enter here",
        )

        yahoo_password = st.text_input(
            "Yahoo App Password",
            value=env_password,
            type="password",
            help="Set YAHOO_APP_PASSWORD in .env or enter here",
        )

        if env_email and env_password:
            st.caption("Pre-filled from .env file")

        policy_number = st.text_input(
            "Policy Number",
            value="",
            help="Policy number to search across inbox and sent",
            placeholder="e.g. 31-23-XXXXXXX",
        )

        claim_numbers = st.text_input(
            "Claim/Pre-auth Numbers (comma-separated)",
            value="",
            help="Claim or pre-auth IDs to include in search",
            placeholder="e.g. 112258XXXXXXX",
        )

        insurer_display_name = st.text_input(
            "Insurer display name",
            value="Aditya Birla Health Insurance",
        )

        exclude_marketing = st.checkbox("Exclude non-claim emails (renewals, onboarding, marketing)", value=True)

        if st.button("Connect & Fetch Emails", width="stretch"):
            if not yahoo_email or not yahoo_password:
                st.error("Enter both Yahoo email and app password, or set them in .env")
            else:
                try:
                    with st.spinner("Connecting to Yahoo Mail..."):
                        client = YahooEmailClient(
                            email=yahoo_email,
                            app_password=yahoo_password,
                        )
                        client.connect_imap()

                    st.success("Connected!")
                    st.session_state.connected = True

                    with st.spinner("Fetching claim emails from inbox..."):
                        # Search by policy number AND claim numbers across inbox
                        search_terms = [policy_number] + [c.strip() for c in claim_numbers.split(",") if c.strip()]
                        all_received = {}

                        for term in search_terms:
                            # Search by subject
                            results = client.search_by_subject(term, folder="INBOX", limit=100)
                            for e in results:
                                if e.id not in all_received:
                                    all_received[e.id] = e

                        # Also search by sender for known insurer addresses (once, outside loop)
                        for sender in ["abhi.grievance", "carehead.healthinsurance", "Communications.Abh"]:
                            sender_results = client.search_by_sender(sender, limit=50)
                            for e in sender_results:
                                if e.id not in all_received:
                                    all_received[e.id] = e

                        received_all = list(all_received.values())

                        # Separate: emails FROM insurer vs FROM family (Pratham's drafts to Papa)
                        insurer_domains = [
                            "adityabirlacapital",   # grievance/care emails
                            "adityabirlahealth",    # claim notifications (Communications.Abh@)
                            "hiadityabirlacapital",
                            "policybazaar",
                        ]

                        received = [
                            e for e in received_all
                            if any(d in e.from_addr.lower() for d in insurer_domains)
                        ]

                        # Exclude non-claim emails (marketing, renewals, policy application/onboarding)
                        if exclude_marketing:
                            exclude_keywords = [
                                # Marketing / renewal
                                "renewal", "healthreturns", "activ health app",
                                "healthy habits", "join the challenge",
                                "sum insured", "no claim bonus",
                                "dedicated manager", "earn no claim",
                                "due for renewal", "increase your sum",
                                "successfully renewed", "premium receipted",
                                # Policy application / onboarding (not claim-related)
                                "welcome onboard",
                                "application is accepted", "application for health insurance",
                                "application is under evaluation",
                                "telephonic medical verification",
                                "premium receipt acknowledgement",
                                "for your health insurance application",
                                # Policybazaar non-claim
                                "2 hour hospitalization",
                                "service calls from policybazaar",
                                "schedule a callback",
                            ]
                            received = [
                                e for e in received
                                if not any(kw in e.subject.lower() for kw in exclude_keywords)
                            ]
                            # Also exclude Policybazaar emails from before the claim period
                            # (policy application/onboarding emails that slip through keyword filter)
                            received = [
                                e for e in received
                                if not ("policybazaar" in e.from_addr.lower() and
                                        hasattr(e, 'date') and e.date and e.date < "2025-07-01")
                            ]

                    st.info(f"Found {len(received)} claim emails from insurer (filtered from {len(received_all)} total)")

                    with st.spinner("Fetching sent emails..."):
                        # Search Sent folder by subject (much faster than fetching all)
                        all_sent = {}
                        for term in search_terms:
                            results = client.search_by_subject(term, folder="Sent", limit=100)
                            for e in results:
                                if e.id not in all_sent:
                                    all_sent[e.id] = e

                        # Filter: only keep emails TO the insurer (exclude internal forwards to Pratham)
                        insurer_to_addresses = ["adityabirla", "abhi.grievance", "carehead"]
                        sent_filtered = [
                            e for e in all_sent.values()
                            if any(addr in e.to_addr.lower() for addr in insurer_to_addresses)
                        ]

                    st.success(f"Fetched {len(received)} received from insurer, {len(sent_filtered)} sent to insurer")

                    # Analyze
                    analyzer = EmailAnalyzer()
                    result = analyzer.analyze(
                        received_emails=received,
                        sent_emails=sent_filtered,
                        insurer_name=insurer_display_name,
                    )
                    st.session_state.analysis_result = result

                    # Save for future use
                    _save_analysis(result)

                    client.close()

                except Exception as e:
                    st.error(f"Connection failed: {e}")
                    import traceback
                    st.code(traceback.format_exc())

    else:
        st.subheader("Load Saved Analysis")
        saved_files = list(Path("data/analysis").glob("*.json")) if Path("data/analysis").exists() else []

        if saved_files:
            selected = st.selectbox(
                "Select analysis file",
                saved_files,
                format_func=lambda p: p.stem,
            )
            if st.button("📂 Load", width="stretch"):
                result = _load_analysis(selected)
                if result:
                    st.session_state.analysis_result = result
                    st.success("Loaded!")
        else:
            st.warning("No saved analyses found. Connect to Yahoo Mail first.")

            # Option to load demo data
            if st.button("📊 Load Demo Data", width="stretch"):
                st.session_state.analysis_result = _generate_demo_data()
                st.success("Demo data loaded!")

    st.divider()
    st.caption("Built with ClaimFlow AI")
    st.caption("[GitHub](https://github.com) | [LinkedIn](https://linkedin.com)")


# ──────────────────────────────────────────────
# Main Dashboard
# ──────────────────────────────────────────────

result = st.session_state.analysis_result

if result is None:
    # Landing page
    st.markdown("""
    # ClaimFlow AI

    ### Insurance Claim Resolution Intelligence

    Connect your Yahoo Mail account to analyze communication patterns
    with your insurer. The system will detect:

    - **Repeated/templated responses** that indicate no human review
    - **Response time gaps** showing delays in grievance redressal
    - **Template phrases** used across multiple emails
    - **Timeline visualization** of your complete interaction

    ---

    **Get started:** Use the sidebar to connect your Yahoo Mail or load demo data.
    """)
    st.stop()


# ──────────────────────────────────────────────
# Header
# ──────────────────────────────────────────────

insurer_name = _get_value(result, "insurer_name", "Insurer")
st.markdown(f"# 📊 Claim Communication Analysis")
st.markdown(f"### {insurer_name}")
st.divider()


# ──────────────────────────────────────────────
# Key Metrics Row
# ──────────────────────────────────────────────

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    total_received = _get_value(result, "total_emails_received", 0)
    st.metric("Emails Received", total_received)

with col2:
    total_sent = _get_value(result, "total_emails_sent", 0)
    st.metric("Emails Sent", total_sent)

with col3:
    unique = _get_value(result, "unique_responses", 0)
    st.metric("Unique Responses", unique, delta=f"of {total_received}", delta_color="off")

with col4:
    rep_rate = _get_value(result, "repetition_rate", 0)
    st.metric("Repetition Rate", f"{rep_rate:.0%}")

with col5:
    days = _get_value(result, "total_days_elapsed", 0)
    st.metric("Days Unresolved", days)


st.divider()


# ──────────────────────────────────────────────
# Key Findings
# ──────────────────────────────────────────────

st.subheader("🔍 Key Findings")

findings = _get_value(result, "key_findings", [])
for finding in findings:
    st.markdown(f"""
    <div class="finding-card">
        {finding}
    </div>
    """, unsafe_allow_html=True)


st.divider()


# ──────────────────────────────────────────────
# Communication Timeline
# ──────────────────────────────────────────────

st.subheader("📅 Communication Timeline")

timeline = _get_value(result, "timeline", [])

if timeline:
    # Build timeline dataframe
    timeline_data = []
    for entry in timeline:
        if isinstance(entry, dict):
            date = entry.get("date", "")
            direction = entry.get("direction", "")
            subject = entry.get("subject", "")
            is_templated = entry.get("is_templated", False)
            response_time = entry.get("response_time_hours")
            body_preview = entry.get("body_preview", "")
        else:
            date = entry.date
            direction = entry.direction
            subject = entry.subject
            is_templated = entry.is_templated
            response_time = entry.response_time_hours
            body_preview = entry.body_preview

        try:
            dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
        except Exception:
            continue

        timeline_data.append({
            "Date": dt,
            "Direction": "⬅️ Received" if direction == "incoming" else "➡️ Sent",
            "Direction_Raw": direction,
            "Subject": subject,
            "Preview": body_preview[:100],
            "Templated": "🔴 Yes" if is_templated else "🟢 No",
            "Is_Templated": is_templated,
            "Response Time (hrs)": response_time or 0,
            "Y_Position": 1 if direction == "incoming" else -1,
        })

    df = pd.DataFrame(timeline_data)

    if not df.empty:
        # Timeline scatter plot
        fig = go.Figure()

        # Incoming emails (from insurer)
        incoming = df[df["Direction_Raw"] == "incoming"]
        outgoing = df[df["Direction_Raw"] == "outgoing"]

        # Incoming - templated
        inc_template = incoming[incoming["Is_Templated"]]
        inc_unique = incoming[~incoming["Is_Templated"]]

        if not inc_template.empty:
            fig.add_trace(go.Scatter(
                x=inc_template["Date"],
                y=[1] * len(inc_template),
                mode="markers",
                marker=dict(size=16, color="#e94560", symbol="circle"),
                name="Insurer - Templated Response",
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>",
                customdata=list(zip(inc_template["Subject"], inc_template["Preview"])),
            ))

        if not inc_unique.empty:
            fig.add_trace(go.Scatter(
                x=inc_unique["Date"],
                y=[1] * len(inc_unique),
                mode="markers",
                marker=dict(size=16, color="#0db39e", symbol="circle"),
                name="Insurer - Unique Response",
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>",
                customdata=list(zip(inc_unique["Subject"], inc_unique["Preview"])),
            ))

        # Outgoing emails
        if not outgoing.empty:
            fig.add_trace(go.Scatter(
                x=outgoing["Date"],
                y=[-1] * len(outgoing),
                mode="markers",
                marker=dict(size=14, color="#4361ee", symbol="diamond"),
                name="You - Sent",
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>",
                customdata=list(zip(outgoing["Subject"], outgoing["Preview"])),
            ))

        # Center line
        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.3)

        fig.update_layout(
            title="Email Timeline: You vs Insurer",
            xaxis_title="Date",
            yaxis=dict(
                tickvals=[-1, 1],
                ticktext=["You (Sent)", f"{insurer_name} (Received)"],
                range=[-2, 2],
            ),
            height=400,
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(10,10,26,0.8)",
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            hovermode="closest",
        )

        st.plotly_chart(fig, width="stretch")

        # Detailed timeline table
        with st.expander("📋 Detailed Timeline"):
            display_df = df[["Date", "Direction", "Subject", "Templated", "Response Time (hrs)"]].copy()
            display_df["Date"] = pd.to_datetime(display_df["Date"]).dt.strftime("%Y-%m-%d %H:%M")
            st.dataframe(display_df, width="stretch", hide_index=True)


st.divider()


# ──────────────────────────────────────────────
# Repetition Analysis
# ──────────────────────────────────────────────

st.subheader("🔄 Response Repetition Analysis")

col_left, col_right = st.columns(2)

with col_left:
    # Pie chart: unique vs repeated
    unique = _get_value(result, "unique_responses", 0)
    repeated = _get_value(result, "repeated_responses", 0)

    if unique + repeated > 0:
        fig_pie = go.Figure(data=[go.Pie(
            labels=["Unique Responses", "Repeated/Templated"],
            values=[unique, repeated],
            hole=0.5,
            marker_colors=["#0db39e", "#e94560"],
            textinfo="label+value",
            textfont_size=14,
        )])

        fig_pie.update_layout(
            title=f"Response Quality Breakdown",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            height=350,
            showlegend=False,
            annotations=[dict(
                text=f"{_get_value(result, 'repetition_rate', 0):.0%}<br>Repeated",
                x=0.5, y=0.5, font_size=20, showarrow=False,
                font_color="#e94560",
            )],
        )

        st.plotly_chart(fig_pie, width="stretch")

with col_right:
    # Template phrases bar chart
    phrases = _get_value(result, "template_phrases_found", {})

    if phrases:
        fig_bar = go.Figure(data=[go.Bar(
            x=list(phrases.values()),
            y=[f'"{p}"' for p in phrases.keys()],
            orientation="h",
            marker_color="#e94560",
        )])

        fig_bar.update_layout(
            title="Template Phrases Detected Across Emails",
            xaxis_title="Times Found",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            height=350,
            yaxis=dict(autorange="reversed"),
        )

        st.plotly_chart(fig_bar, width="stretch")


# ──────────────────────────────────────────────
# Email Groups
# ──────────────────────────────────────────────

st.divider()
st.subheader("📧 Response Groups (Grouped by Content Similarity)")

groups = _get_value(result, "email_groups", [])

for i, group in enumerate(groups):
    if isinstance(group, dict):
        count = group.get("count", 0)
        subject = group.get("subject", "")
        preview = group.get("body_preview", "")
        first = group.get("first_seen", "")[:10]
        last = group.get("last_seen", "")[:10]
    else:
        count = group.count
        subject = group.representative_subject
        preview = group.representative_body_preview
        first = group.first_seen[:10]
        last = group.last_seen[:10]

    badge_color = "#e94560" if count > 1 else "#0db39e"
    times_text = "time" if count == 1 else "times"

    with st.expander(f"**{subject}** — Sent **{count}** {times_text} ({first} → {last})"):
        st.markdown(f"""
        **Count:** <span style="color:{badge_color};font-size:24px;font-weight:bold">{count}</span> identical/near-identical emails

        **Date Range:** {first} to {last}

        **Content Preview:**
        > {preview}
        """, unsafe_allow_html=True)


# ──────────────────────────────────────────────
# Response Time Analysis
# ──────────────────────────────────────────────

st.divider()
st.subheader("⏱️ Response Time Analysis")

if timeline:
    response_times = []
    for entry in timeline:
        if isinstance(entry, dict):
            rt = entry.get("response_time_hours")
            direction = entry.get("direction")
            date = entry.get("date", "")
        else:
            rt = entry.response_time_hours
            direction = entry.direction
            date = entry.date

        if rt and rt > 0 and direction == "incoming":
            try:
                dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
                response_times.append({"Date": dt, "Response Time (hours)": rt, "Days": rt / 24})
            except Exception:
                pass

    if response_times:
        rt_df = pd.DataFrame(response_times)

        fig_rt = go.Figure()
        fig_rt.add_trace(go.Bar(
            x=rt_df["Date"],
            y=rt_df["Days"],
            marker_color=["#e94560" if d > 7 else "#fca311" if d > 3 else "#0db39e" for d in rt_df["Days"]],
            hovertemplate="Response took: %{y:.1f} days<extra></extra>",
        ))

        fig_rt.update_layout(
            title="Insurer Response Time (Days)",
            xaxis_title="Date",
            yaxis_title="Days to Respond",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            height=350,
        )

        # Add benchmark line
        fig_rt.add_hline(
            y=15, line_dash="dash", line_color="yellow", opacity=0.5,
            annotation_text="IRDAI 15-day guideline",
            annotation_position="top right",
        )

        st.plotly_chart(fig_rt, width="stretch")


# ──────────────────────────────────────────────
# Export Section
# ──────────────────────────────────────────────

st.divider()
st.subheader("📤 Export for LinkedIn")

if st.button("Generate LinkedIn Summary", width="stretch"):
    total_received = _get_value(result, "total_emails_received", 0)
    unique = _get_value(result, "unique_responses", 0)
    repeated = _get_value(result, "repeated_responses", 0)
    rep_rate = _get_value(result, "repetition_rate", 0)
    days = _get_value(result, "total_days_elapsed", 0)

    linkedin_text = f"""📊 Data doesn't lie. Here's what {days} days of "grievance redressal" looks like:

📩 Emails I sent: {_get_value(result, 'total_emails_sent', 0)}
📨 Replies received: {total_received}
🔁 Of those, identical/templated: {repeated} ({rep_rate:.0%})
🆕 Actually unique responses: {unique}
⏱️ Average response time: {_get_value(result, 'avg_response_time_hours', 0) / 24:.0f} days

Zero medical causality analysis. Zero precedent review. Zero escalation to compliance.

3 months ago I shared my story. Today I'm sharing data.

I built an AI system that reads every email, detects templates, matches precedents, and tracks patterns. It took 30 seconds to find what {insurer_name}'s team couldn't find in {days} days.

The tool is open source. If you're stuck in the same loop, DM me.

#InsurTech #HealthInsurance #AgenticAI #BuildInPublic"""

    st.text_area("Copy this for your LinkedIn post:", linkedin_text, height=400)
    st.info("Take a screenshot of the dashboard charts to attach to your post!")


# ──────────────────────────────────────────────
# Footer
# ──────────────────────────────────────────────

st.divider()
st.caption(
    "ClaimFlow AI — Built as a social experiment to understand insurance claim resolution patterns. "
    "Data is analyzed locally. No personal information is shared."
)
