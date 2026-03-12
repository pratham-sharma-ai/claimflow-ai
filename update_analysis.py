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

def main():
    mail = connect()
    print("[+] Connected\n")

    all_received = {}  # keyed by (date, subject) to dedup
    all_sent = {}

    # ──────────────────────────────────────────
    # INBOX: Search by multiple criteria
    # ──────────────────────────────────────────

    searches = [
        # By claim ID in subject
        ('INBOX', 'SUBJECT "1122585253392"', "claim ID"),
        # By pre-auth ID in subject
        ('INBOX', 'SUBJECT "1112585238669"', "pre-auth ID"),
        # By policy number in subject
        ('INBOX', 'SUBJECT "31-23-0060869"', "policy number"),
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
        # Policybazaar with policy number
        ('INBOX', 'FROM "policybazaar" SUBJECT "31-23-0060869"', "policybazaar+policy"),
        # Policybazaar renewal
        ('INBOX', 'FROM "policybazaar" SUBJECT "renewal"', "policybazaar+renewal"),
        # Policybazaar with Ref ID
        ('INBOX', 'FROM "policybazaar" SUBJECT "1042851178"', "policybazaar+refid"),
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

    sent_searches = [
        ('Sent', 'SUBJECT "31-23-0060869"', "sent+policy"),
        ('Sent', 'SUBJECT "1122585253392"', "sent+claim"),
        ('Sent', 'SUBJECT "1112585238669"', "sent+preauth"),
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

    # Exclude pure marketing noise (not related to the claim or renewal contradiction)
    noise_keywords = [
        "healthreturns", "activ health app", "healthy habits",
        "join the challenge", "earn no claim",
        "dedicated manager", "welcome onboard",
        "application is accepted", "application for health insurance",
        "application is under evaluation", "telephonic medical verification",
        "premium receipt acknowledgement", "for your health insurance application",
        "schedule a callback", "service calls from policybazaar",
        "2 hour hospitalization",
        # Generic PB marketing
        "checklist for a stress-free",
    ]

    # Filter received emails
    filtered_received = []
    for r in sorted(all_received.values(), key=lambda x: x["date"]):
        from_addr = r["from"].lower()
        subject_lower = r["subject"].lower()

        # Must be from insurer or policybazaar
        is_insurer = any(d in from_addr for d in insurer_domains)
        is_policybazaar = policybazaar_domain in from_addr

        if not is_insurer and not is_policybazaar:
            print(f"  SKIP (not insurer): [{r['date'][:10]}] {r['subject'][:60]}")
            continue

        # Filter out pre-claim emails (before July 2025)
        if r["date"] < "2025-07-01":
            print(f"  SKIP (pre-claim): [{r['date'][:10]}] {r['subject'][:60]}")
            continue

        # For Policybazaar: only keep renewal notices for THIS policy
        # (proves the contradiction — renewing a voided policy)
        if is_policybazaar:
            has_policy_num = "31-23-0060869" in r["subject"]
            has_ref_id = "1042851178" in r["subject"]
            is_renewal = "renewal" in subject_lower
            # Keep if: (policy number + renewal) OR (ref ID + renewal)
            if not ((has_policy_num and is_renewal) or (has_ref_id and is_renewal)):
                print(f"  SKIP (PB not policy-renewal): [{r['date'][:10]}] {r['subject'][:60]}")
                continue

        # Filter out noise
        if any(kw in subject_lower for kw in noise_keywords):
            print(f"  SKIP (noise): [{r['date'][:10]}] {r['subject'][:60]}")
            continue

        # Determine direction
        r["direction"] = "incoming"
        r["is_templated"] = False

        # Mark as templated: check BOTH subject AND body for template indicators
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

        if any(phrase in subject_lower for phrase in template_subject_markers):
            r["is_templated"] = True
        elif any(phrase in r["body_preview"].lower() for phrase in template_body_markers):
            r["is_templated"] = True

        filtered_received.append(r)
        print(f"  KEEP: [{r['date'][:10]}] {r['subject'][:70]} {'[TEMPLATED]' if r['is_templated'] else ''}")

    # Filter sent: only emails TO the insurer (not forwards to family)
    insurer_to_addrs = ["adityabirla", "abhi.grievance", "carehead", "gro.health"]
    filtered_sent = []
    for r in sorted(all_sent.values(), key=lambda x: x["date"]):
        to_addr = r.get("to", "").lower()
        if any(addr in to_addr for addr in insurer_to_addrs):
            r["direction"] = "outgoing"
            r["is_templated"] = False
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

    # Calculate days elapsed
    if all_timeline:
        first_dt = datetime.fromisoformat(all_timeline[0]["date"].replace("Z", "+00:00"))
        last_dt = datetime.fromisoformat(all_timeline[-1]["date"].replace("Z", "+00:00"))
        days_elapsed = (last_dt - first_dt).days
    else:
        days_elapsed = 0

    # Count templated vs unique
    templated_count = sum(1 for r in filtered_received if r.get("is_templated"))
    unique_count = len(filtered_received) - templated_count
    rep_rate = templated_count / len(filtered_received) if filtered_received else 0

    # Build key findings
    key_findings = [
        f"{rep_rate:.0%} of insurer responses are templated repeats.",
        f'The phrase "we regret to inform" appeared in {template_phrases.get("we regret to inform", 0)} emails.',
        f"Documents were requested 3 times in 8 days — after being told they don't exist.",
        f"Issue has been open for {days_elapsed} days with no resolution.",
        f"The insurer voided the policy in Oct 2025, then sent a renewal payment notice in Jan 2026.",
        f"Policybazaar is still sending renewal reminders as of this week for the voided policy.",
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
        })

    # Build final analysis
    analysis = {
        "insurer_name": "Aditya Birla Health Insurance",
        "total_emails_received": len(filtered_received),
        "total_emails_sent": len(filtered_sent),
        "unique_responses": unique_count,
        "repeated_responses": templated_count,
        "repetition_rate": rep_rate,
        "avg_response_time_hours": 0,  # complex to calculate, keep 0
        "max_response_gap_days": 0,
        "template_phrases_found": template_phrases,
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
                "response_time_hours": None,
            }
            for r in all_timeline
        ],
        "email_groups": email_groups,
    }

    # Save
    out_path = Path("data/analysis/clean_analysis.json")
    out_path.write_text(json.dumps(analysis, indent=2, ensure_ascii=False))

    print(f"\n{'='*60}")
    print(f"SAVED: {out_path}")
    print(f"  Received: {len(filtered_received)}")
    print(f"  Sent: {len(filtered_sent)}")
    print(f"  Templated: {templated_count}")
    print(f"  Unique: {unique_count}")
    print(f"  Repetition rate: {rep_rate:.0%}")
    print(f"  Days elapsed: {days_elapsed}")
    print(f"  Template phrases: {template_phrases}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
