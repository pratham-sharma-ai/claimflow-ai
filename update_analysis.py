"""
Fetch missing emails and rebuild clean_analysis.json with complete data.
"""
import imaplib
import email
from email.header import decode_header
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

YAHOO_EMAIL = os.getenv("YAHOO_EMAIL")
YAHOO_PASSWORD = os.getenv("YAHOO_APP_PASSWORD")

def connect():
    mail = imaplib.IMAP4_SSL("imap.mail.yahoo.com")
    mail.login(YAHOO_EMAIL, YAHOO_PASSWORD)
    return mail

def decode_subject(msg):
    subject = msg.get("Subject", "")
    decoded = decode_header(subject)
    parts = []
    for data, charset in decoded:
        if isinstance(data, bytes):
            parts.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(data)
    return " ".join(parts)

def get_body(msg, max_len=800):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
                    break
            elif ct == "text/html" and not body:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
    return body[:max_len]

def fetch_emails_by_search(mail, folder, criteria):
    """Search and fetch emails matching criteria."""
    mail.select(folder, readonly=True)
    status, data = mail.search(None, criteria)
    if status != "OK" or not data[0]:
        return []

    results = []
    ids = data[0].split()
    for eid in ids:
        status, msg_data = mail.fetch(eid, "(RFC822)")
        if status != "OK":
            continue
        msg = email.message_from_bytes(msg_data[0][1])

        date_str = msg.get("Date", "")
        from_addr = msg.get("From", "")
        to_addr = msg.get("To", "")
        subject = decode_subject(msg)
        body = get_body(msg)

        # Parse date
        try:
            dt = email.utils.parsedate_to_datetime(date_str)
        except Exception:
            continue

        results.append({
            "date": dt.isoformat(),
            "from": from_addr,
            "to": to_addr,
            "subject": subject,
            "body_preview": body,
            "imap_id": eid.decode()
        })

    return results

def main(policy_number="", claim_numbers="", insurer_name=""):
    mail = connect()
    print("[+] Connected\n")

    all_received = {}  # keyed by (date, subject) to dedup
    all_sent = {}

    # ──────────────────────────────────────────
    # INBOX: Search by multiple criteria
    # ──────────────────────────────────────────

    # Build dynamic searches from user-provided policy/claim numbers
    dynamic_searches = []
    if claim_numbers:
        for cn in claim_numbers.split(","):
            cn = cn.strip()
            if cn:
                dynamic_searches.append(('INBOX', f'SUBJECT "{cn}"', f"claim ID {cn}"))
    if policy_number:
        dynamic_searches.append(('INBOX', f'SUBJECT "{policy_number}"', "policy number"))

    searches = dynamic_searches + [
        # By sender: Communications.Abh (renewal notices, claim emails)
        ('INBOX', 'FROM "Communications.Abh"', "Communications.Abh"),
        # By sender: abhi.grievance
        ('INBOX', 'FROM "abhi.grievance"', "abhi.grievance"),
        # By sender: carehead
        ('INBOX', 'FROM "carehead"', "carehead"),
        # By sender: abhi.service (IGMS auto-reply)
        ('INBOX', 'FROM "abhi.service"', "abhi.service"),
        # By sender: abhicl.renewal (renewal team emails)
        ('INBOX', 'FROM "abhicl.renewal"', "abhicl.renewal"),
        # By sender: care.healthinsurance (policy docs, renewal confirmation)
        ('INBOX', 'FROM "care.healthinsurance"', "care.healthinsurance"),
        # Broader: any email from abhiservice domain
        ('INBOX', 'FROM "abhiservice"', "abhiservice_domain"),
        # Broad catch-all: any email from adityabirla
        ('INBOX', 'FROM "adityabirla"', "adityabirla_catchall"),
        # Another ABHI domain variant
        ('INBOX', 'FROM "hiadityabirlacapital"', "hiadityabirlacapital"),
        # Catch all abhicl.* senders (marketing, renewal, etc.)
        ('INBOX', 'FROM "abhicl"', "abhicl_catchall"),
        # ALL Policybazaar emails (not just renewal)
        ('INBOX', 'FROM "policybazaar"', "policybazaar_all"),
    ]

    for folder, criteria, label in searches:
        print(f"  Searching {label}...")
        results = fetch_emails_by_search(mail, folder, criteria)
        for r in results:
            key = (r["date"][:19], r["subject"][:80], r["imap_id"])
            if key not in all_received:
                all_received[key] = r
                print(f"    + [{r['date'][:10]}] {r['subject'][:80]}")

    print(f"\n  Total unique received: {len(all_received)}\n")

    # ──────────────────────────────────────────
    # SENT folder
    # ──────────────────────────────────────────

    dynamic_sent = []
    if policy_number:
        dynamic_sent.append(('Sent', f'SUBJECT "{policy_number}"', "sent+policy"))
    if claim_numbers:
        for cn in claim_numbers.split(","):
            cn = cn.strip()
            if cn:
                dynamic_sent.append(('Sent', f'SUBJECT "{cn}"', f"sent+claim_{cn}"))

    sent_searches = dynamic_sent + [
        ('Sent', 'TO "adityabirla"', "sent+to_abhi"),
        ('Sent', 'TO "abhi.grievance"', "sent+to_grievance"),
        ('Sent', 'TO "carehead"', "sent+to_carehead"),
    ]

    for folder, criteria, label in sent_searches:
        print(f"  Searching {label}...")
        results = fetch_emails_by_search(mail, folder, criteria)
        for r in results:
            key = (r["date"][:16], r["subject"][:50])
            if key not in all_sent:
                all_sent[key] = r
                print(f"    + [{r['date'][:10]}] {r['subject'][:80]}")

    print(f"\n  Total unique sent: {len(all_sent)}\n")

    mail.logout()

    # ──────────────────────────────────────────
    # Filter and classify
    # ──────────────────────────────────────────

    insurer_domains = [
        "adityabirlacapital", "adityabirlahealth",
        "hiadityabirlacapital", "abhiservice",
    ]
    policybazaar_domain = "policybazaar"

    # ──────────────────────────────────────────
    # Categorization keywords
    # ──────────────────────────────────────────

    claim_subject_keywords = [
        "could not be processed", "additional documents required",
        "supporting documents", "grievance", "repudiat",
        "pre-auth", "cashless", "reimbursement",
        "claim id", "claim no", "your claim", "claim number",
        "existing claims", "your policy number",
    ]
    # Phrases that contain "claim" but are NOT claim-related
    claim_false_positives = [
        "no claim bonus", "earn no claim",
        "a claim by lunch", "claim rejected? maybe not",
    ]
    claim_body_keywords = [
        "we regret to inform", "unable to approve the claim",
        "could not be processed", "is repudiated",
        "our decision remains unchanged", "claim stands rejected",
        "non-disclosure", "pre-existing",
    ]
    renewal_keywords = [
        "renewal", "is due for renewal", "renew", "premium due",
        "successfully renewed", "premium notice", "pay premium",
        "policy is active", "policy is continue",
    ]
    marketing_keywords = [
        "healthreturns", "activ health app", "healthy habits",
        "join the challenge", "earn no claim", "no claim bonus",
        "dedicated manager", "sum insured", "increase your sum",
        "health check", "wellness", "fitness", "reward",
        "offer", "discount", "cashback", "refer a friend",
        "download the app", "2 hour hospitalization",
        "checklist for a stress-free",
    ]
    admin_keywords = [
        "welcome onboard", "application is accepted",
        "application for health insurance",
        "application is under evaluation",
        "telephonic medical verification",
        "premium receipt acknowledgement",
        "for your health insurance application",
        "schedule a callback", "service calls from policybazaar",
        "policy document", "e-card", "id card",
    ]

    def categorize_email(subject_lower, body_lower, from_addr_lower):
        """Categorize email: claim > renewal > admin > marketing > other."""
        # Check for false positives first (marketing emails containing "claim")
        if any(fp in subject_lower for fp in claim_false_positives):
            pass  # Skip claim check, fall through to other categories
        else:
            # Claim-related (highest priority)
            if any(kw in subject_lower for kw in claim_subject_keywords):
                return "claim"
            if any(kw in body_lower for kw in claim_body_keywords):
                return "claim"
        # Renewal
        if any(kw in subject_lower for kw in renewal_keywords):
            return "renewal"
        if any(kw in body_lower for kw in renewal_keywords):
            return "renewal"
        # Administrative (onboarding, policy docs)
        if any(kw in subject_lower for kw in admin_keywords):
            return "administrative"
        if any(kw in body_lower for kw in admin_keywords):
            return "administrative"
        # Marketing
        if any(kw in subject_lower for kw in marketing_keywords):
            return "marketing"
        if any(kw in body_lower for kw in marketing_keywords):
            return "marketing"
        return "other"

    # Template detection markers
    template_subject_markers = [
        "could not be processed",
        "additional documents required",
        "supporting documents",
        "is due for renewal",
    ]
    template_body_markers = [
        "we regret to inform",
        "unable to approve the claim",
        "could not be processed",
        "is repudiated",
        "our decision remains unchanged",
        "claim stands rejected",
    ]

    # Process ALL received emails — no noise filter, no date filter
    filtered_received = []
    for r in sorted(all_received.values(), key=lambda x: x["date"]):
        from_addr = r["from"].lower()
        subject_lower = r["subject"].lower()
        body_lower = r["body_preview"].lower()

        # Must be from insurer or policybazaar
        is_insurer = any(d in from_addr for d in insurer_domains)
        is_policybazaar = policybazaar_domain in from_addr

        if not is_insurer and not is_policybazaar:
            print(f"  SKIP (not insurer/PB): [{r['date'][:10]}] {r['subject'][:60]}")
            continue

        # Determine direction and categorize
        r["direction"] = "incoming"
        r["category"] = categorize_email(subject_lower, body_lower, from_addr)
        r["is_templated"] = False

        # Mark as templated
        if any(phrase in subject_lower for phrase in template_subject_markers):
            r["is_templated"] = True
        elif any(phrase in body_lower for phrase in template_body_markers):
            r["is_templated"] = True

        filtered_received.append(r)
        print(f"  KEEP [{r['category'].upper():12s}]: [{r['date'][:10]}] {r['subject'][:60]} {'[TEMPLATED]' if r['is_templated'] else ''}")

    # Filter sent: only emails TO the insurer (not forwards to family)
    insurer_to_addrs = ["adityabirla", "abhi.grievance", "carehead", "gro.health"]
    filtered_sent = []
    for r in sorted(all_sent.values(), key=lambda x: x["date"]):
        to_addr = r.get("to", "").lower()
        if any(addr in to_addr for addr in insurer_to_addrs):
            r["direction"] = "outgoing"
            r["is_templated"] = False
            r["category"] = "claim"
            filtered_sent.append(r)
            print(f"  SENT: [{r['date'][:10]}] {r['subject'][:70]}")
        else:
            print(f"  SKIP SENT (not to insurer): [{r['date'][:10]}] {r['subject'][:60]} -> {to_addr[:40]}")

    # ──────────────────────────────────────────
    # Build analysis
    # ──────────────────────────────────────────

    all_timeline = sorted(filtered_received + filtered_sent, key=lambda x: x["date"])

    # Count template phrases
    template_phrases = {}
    for phrase in ["we regret to inform", "could not be processed", "is repudiated", "unable to approve"]:
        count = sum(1 for r in filtered_received if phrase in r.get("body_preview", "").lower())
        if count > 0:
            template_phrases[phrase] = count

    # Calculate days elapsed — from date of hospital admission to latest email
    # Admission date: July 31, 2025 (pre-auth generated same day)
    admission_date = datetime(2025, 7, 31, tzinfo=timezone.utc)
    if all_timeline:
        last_dt = datetime.fromisoformat(all_timeline[-1]["date"].replace("Z", "+00:00"))
        days_elapsed = (last_dt - admission_date).days
    else:
        days_elapsed = 0

    # Category counts (received only)
    from collections import Counter
    category_counts = Counter(r.get("category", "other") for r in filtered_received)

    # Count templated vs unique (claim emails only for the core metric)
    claim_received = [r for r in filtered_received if r.get("category") == "claim"]
    templated_count = sum(1 for r in claim_received if r.get("is_templated"))
    unique_count = len(claim_received) - templated_count
    rep_rate = templated_count / len(claim_received) if claim_received else 0

    # Build key findings
    marketing_count = category_counts.get("marketing", 0)
    renewal_count = category_counts.get("renewal", 0)
    admin_count = category_counts.get("administrative", 0)
    claim_count = category_counts.get("claim", 0)

    key_findings = [
        f"{rep_rate:.0%} of claim-related responses are templated repeats.",
        f'The phrase "we regret to inform" appeared in {template_phrases.get("we regret to inform", 0)} emails.',
        f"Documents were requested 3 times in 8 days -- after being told they don't exist.",
        f"Issue has been open for {days_elapsed} days with no resolution.",
        f"The insurer voided the policy in Oct 2025, then sent a renewal payment notice in Jan 2026.",
        f"Policybazaar is still sending renewal reminders as of this week for the voided policy.",
        f"While ignoring the claim, the insurer sent {marketing_count} marketing emails and {renewal_count} renewal notices.",
    ]

    # Build email groups (group by similar subject)
    from collections import defaultdict
    groups = defaultdict(list)
    for r in filtered_received:
        # Normalize subject for grouping
        subj = r["subject"].strip()
        # Remove Re:/Fw: prefixes
        for prefix in ["Re: ", "Fw: ", "RE: ", "FW: "]:
            if subj.startswith(prefix):
                subj = subj[len(prefix):]
        groups[subj].append(r)

    email_groups = []
    for subj, emails in sorted(groups.items(), key=lambda x: -len(x[1])):
        email_groups.append({
            "count": len(emails),
            "subject": subj,
            "body_preview": emails[0]["body_preview"][:300],
            "first_seen": emails[0]["date"],
            "last_seen": emails[-1]["date"],
            "category": emails[0].get("category", "other"),
        })

    # Build final analysis
    analysis = {
        "insurer_name": insurer_name or "Insurance Company",
        "total_emails_received": len(filtered_received),
        "total_emails_sent": len(filtered_sent),
        "claim_emails_received": claim_count,
        "marketing_emails_received": marketing_count,
        "renewal_emails_received": renewal_count,
        "admin_emails_received": admin_count,
        "other_emails_received": category_counts.get("other", 0),
        "unique_responses": unique_count,
        "repeated_responses": templated_count,
        "repetition_rate": rep_rate,
        "avg_response_time_hours": 0,
        "max_response_gap_days": 0,
        "template_phrases_found": template_phrases,
        "category_counts": dict(category_counts),
        "first_email_date": all_timeline[0]["date"] if all_timeline else "",
        "last_email_date": all_timeline[-1]["date"] if all_timeline else "",
        "total_days_elapsed": days_elapsed,
        "key_findings": key_findings,
        "timeline": [
            {
                "date": r["date"],
                "direction": r["direction"],
                "subject": r["subject"],
                "body_preview": r["body_preview"][:200],
                "is_templated": r.get("is_templated", False),
                "category": r.get("category", "other"),
                "response_time_hours": None,
            }
            for r in all_timeline
        ],
        "email_groups": email_groups,
    }

    # Save
    out_path = Path("data/analysis/clean_analysis.json")
    out_path.write_text(json.dumps(analysis, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"SAVED: {out_path}")
    print(f"  Total Received: {len(filtered_received)}")
    print(f"    Claim:         {claim_count}")
    print(f"    Marketing:     {marketing_count}")
    print(f"    Renewal:       {renewal_count}")
    print(f"    Administrative:{admin_count}")
    print(f"    Other:         {category_counts.get('other', 0)}")
    print(f"  Total Sent: {len(filtered_sent)}")
    print(f"  Claim Templated: {templated_count}")
    print(f"  Claim Unique: {unique_count}")
    print(f"  Claim Repetition rate: {rep_rate:.0%}")
    print(f"  Days elapsed: {days_elapsed}")
    print(f"  Template phrases: {template_phrases}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
