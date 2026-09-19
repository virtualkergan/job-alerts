# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A daily job-alert bot: `main.py` polls company career sites, diffs against `state.json`, and emails new postings via SMTP. It runs in GitHub Actions (`.github/workflows/daily-job-alert.yml`), which commits the updated `state.json` back to `main` after each run — so `state.json` changes (and "Update job alert state" commits) are normal, expected churn.

## Commands

```bash
pip install -r requirements.txt
python main.py --dry-run          # fetch + diff + print the email; no send, no state.json write
python main.py                    # sends email; needs SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, ALERT_TO env vars
python test_connectors.py         # live-network smoke test of every connector (prints count + first 3)
python test_connectors.py "Aon"   # one company, by exact `name` from companies.yaml
```

There is no unit-test suite or linter; `test_connectors.py` hits the real sites.

## Architecture

- `companies.yaml` is a list of company dicts. `platform` selects a connector from the `CONNECTORS` dict in `main.py`; the remaining keys are that connector's config. Optional `keywords` is a case-insensitive substring filter on job titles, applied in `main.py` (not in connectors).
- Each connector in `connectors/` exposes `fetch_jobs(company_cfg) -> list[dict]`, returning dicts with `id`, `title`, `url`, `location`, `posted`. `id` must be stable across runs — it is what `state.json` stores (per company name → sorted list of ids). Adding a new platform means a new connector module plus registering it in `CONNECTORS` in `main.py`.
- Connectors: `workday` (JSON POST endpoint; currently no company uses it), `attract_api` (iCIMS-backed `/api/jobs`, shared by Aon and First Citizens), `html_scrape` (generic link scraper with `page_param`/`offset_param`/`none` pagination and optional `link_pattern` regex), `marsh_phenom` (one specific Phenom `/widgets` payload for careers.marsh.com).
- `state.json` is keyed by company `name`, so renaming a company in `companies.yaml` re-seeds its baseline.

## Behaviors that aren't obvious

- **First run per company seeds a baseline**: if `name` isn't in `state.json`, its postings are recorded but not reported as new.
- **Connector errors are isolated**: a failing company is logged to stderr and its state is left untouched. The run still exits non-zero at the end (even with no new postings, after any email is sent), and the workflow's commit step uses `if: always()`, so state is saved and a broken connector shows up as a failed run.
- **State is the full current set, not cumulative**: `state[name] = current_ids` replaces the old list, so a posting that disappears and reappears is reported as new again. A partial/truncated fetch (e.g. scraper stopping early on a blocked page) silently drops ids and can cause re-alerts later.
- `html_scrape` uses the full listing-page URL as the job `id`, and its default link regex requires ≥3 hyphenated words in a `/job(s)/` path to avoid nav links; sites with other URL shapes need `link_pattern`.
- `marsh_phenom`: `from` must be in both the query string and the JSON body or the server always returns page 1.
- The cron is `47 11 * * *` UTC (7:47am EDT) and doesn't adjust for DST.
