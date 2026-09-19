"""
Daily job-alert runner.

What it does, every time it runs:
  1. Loads companies.yaml
  2. For each company, calls the right connector to get today's open roles
  3. Compares against state.json (what we saw last time)
  4. Emails a digest of anything new, with clickable links
  5. Saves the updated state.json so tomorrow's run only reports *new* jobs

Run manually with:  python main.py
Run without sending email (just print what would happen): python main.py --dry-run
"""
import argparse
import json
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yaml

from connectors import workday, html_scrape, attract_api, marsh_phenom

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "state.json"
COMPANIES_FILE = ROOT / "companies.yaml"

CONNECTORS = {
    "workday": workday.fetch_jobs,
    "html_scrape": html_scrape.fetch_jobs,
    "attract_api": attract_api.fetch_jobs,
    "marsh_phenom": marsh_phenom.fetch_jobs,
}


def load_companies() -> list[dict]:
    with open(COMPANIES_FILE) as f:
        return yaml.safe_load(f)


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def matches_keywords(title: str, keywords: list[str] | None) -> bool:
    if not keywords:
        return True
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


def fetch_new_jobs_for_company(company: dict, seen_ids: set) -> tuple[list[dict], set, str | None]:
    """Returns (new_jobs, all_current_ids, error_message)."""
    platform = company.get("platform")
    connector = CONNECTORS.get(platform)

    if connector is None:
        return [], seen_ids, f"platform '{platform}' not yet configured - skipping"

    try:
        all_jobs = connector(company)
    except Exception as e:  # noqa: BLE001 - one company's failure shouldn't kill the run
        return [], seen_ids, f"fetch failed: {e}"

    relevant = [j for j in all_jobs if matches_keywords(j["title"], company.get("keywords"))]
    current_ids = {j["id"] for j in relevant}
    new_jobs = [j for j in relevant if j["id"] not in seen_ids]

    return new_jobs, current_ids, None


def build_email_html(results: dict[str, list[dict]]) -> str:
    parts = ["<h2>New job postings today</h2>"]
    for company_name, jobs in results.items():
        if not jobs:
            continue
        parts.append(f"<h3>{company_name}</h3><ul>")
        for j in jobs:
            loc = f" — {j['location']}" if j.get("location") else ""
            parts.append(f'<li><a href="{j["url"]}">{j["title"]}</a>{loc}</li>')
        parts.append("</ul>")
    return "\n".join(parts)


def send_email(html_body: str) -> None:
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    to_addr = os.environ.get("ALERT_TO", smtp_user)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your daily job alert"
    msg["From"] = smtp_user
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [to_addr], msg.as_string())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Don't send email, just print results")
    args = parser.parse_args()

    companies = load_companies()
    state = load_state()

    results = {}
    any_errors = False

    for company in companies:
        name = company["name"]
        is_first_run = name not in state
        seen_ids = set(state.get(name, []))
        new_jobs, current_ids, error = fetch_new_jobs_for_company(company, seen_ids)

        if error:
            print(f"[{name}] {error}", file=sys.stderr)
            any_errors = True
            # Don't overwrite state on error, so we don't lose track of
            # what we'd already seen once this company's connector is fixed.
            continue

        # First time seeing this company: record today's postings as the
        # baseline but don't report them all as "new" - only postings that
        # show up on later runs count.
        results[name] = [] if is_first_run else new_jobs
        state[name] = sorted(current_ids)
        tag = " (seeding baseline)" if is_first_run else ""
        print(f"[{name}] {len(current_ids)} matching postings, {len(new_jobs)} new{tag}")

    if not args.dry_run:
        save_state(state)

    total_new = sum(len(v) for v in results.values())
    if total_new == 0:
        print("No new postings today.")
    else:
        html_body = build_email_html(results)

        if args.dry_run:
            print("\n--- DRY RUN: would send this email ---\n")
            print(html_body)
        else:
            send_email(html_body)
            print(f"Sent email with {total_new} new posting(s).")

    if any_errors:
        sys.exit(1)  # non-zero exit surfaces the failure in GitHub Actions' UI


if __name__ == "__main__":
    main()
