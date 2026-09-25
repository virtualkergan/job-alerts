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
import html
import json
import os
import smtplib
import sys
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yaml

from connectors import workday, html_scrape, attract_api, marsh_phenom
from jobformat import format_date, format_locations, format_posted, is_us_job, parse_posted

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

    if not all_jobs and seen_ids:
        # An empty list from a company we've seen before almost always means a
        # broken/blocked scrape, not zero openings; keep old state to avoid
        # re-alerting every posting once the connector recovers.
        return [], seen_ids, "connector returned no postings - keeping previous state"

    unique = {}
    for j in all_jobs:
        if matches_keywords(j["title"], company.get("keywords")) and is_us_job(j):
            # setdefault: a connector that repeats a posting still yields it once.
            unique.setdefault(j["id"], j)
    relevant = list(unique.values())
    current_ids = set(unique)
    new_jobs = [j for j in relevant if j["id"] not in seen_ids]

    return new_jobs, current_ids, None


def _sort_key(job: dict):
    posted = parse_posted(job.get("posted", ""))
    # Newest first, undated postings last, then alphabetical.
    return (posted is None, -(posted.toordinal() if posted else 0), job["title"].lower())


def build_email_html(results: dict[str, list[dict]]) -> str:
    # Inline styles only: Gmail/Outlook strip <style> blocks.
    companies = {name: jobs for name, jobs in results.items() if jobs}
    total = sum(len(jobs) for jobs in companies.values())
    summary = (
        f"{total} new posting{'s' if total != 1 else ''} at "
        f"{len(companies)} compan{'ies' if len(companies) != 1 else 'y'}"
    )
    parts = [
        '<div style="font-family: Arial, Helvetica, sans-serif; font-size: 14px; color: #222; max-width: 680px;">',
        f'<h2 style="margin: 0 0 4px;">New job postings: {format_date(date.today())}</h2>',
        f'<p style="margin: 0 0 8px; color: #666;">{summary}</p>',
    ]
    for company_name, jobs in companies.items():
        parts.append(
            '<h3 style="margin: 24px 0 10px; padding-bottom: 4px; border-bottom: 1px solid #ddd;">'
            f"{html.escape(company_name)} ({len(jobs)})</h3>"
        )
        for j in sorted(jobs, key=_sort_key):
            meta = [format_locations(j.get("locations", []))]
            posted = format_posted(j.get("posted", ""))
            if posted:
                meta.append(f"Posted {posted}")
            title = " ".join(j["title"].split())
            parts.append(
                '<div style="margin: 0 0 12px;">'
                f'<a href="{html.escape(j["url"])}" style="font-weight: bold; color: #1a0dab; text-decoration: none;">'
                f"{html.escape(title)}</a><br>"
                f'<span style="color: #666; font-size: 13px;">{html.escape(" · ".join(meta))}</span>'
                "</div>"
            )
    parts.append("</div>")
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

    # Saved only after the email succeeds: if sending raises, state stays
    # unchanged so the next run re-reports these postings instead of losing them.
    if not args.dry_run:
        save_state(state)

    if any_errors:
        sys.exit(1)  # non-zero exit surfaces the failure in GitHub Actions' UI


if __name__ == "__main__":
    main()
