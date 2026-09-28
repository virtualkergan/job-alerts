# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A daily job-alert bot: `main.py` polls company career sites, diffs against `state.json`, and emails new postings via SMTP. The scheduled runner is the Docker Compose stack (`compose.yaml` + `Dockerfile`): supercronic runs inside the container, and `state.json` / `companies.yaml` are bind-mounted from the repo dir, so a locally modified `state.json` is normal, expected churn. The GitHub Actions workflow (`.github/workflows/daily-job-alert.yml`) is manual-only (`workflow_dispatch`); when run, it commits `state.json` back to `main` ("Update job alert state" commits).

## Commands

```bash
pip install -r requirements.txt
python main.py --dry-run          # fetch + diff + print the email; no send, no state.json write
python main.py                    # sends email; needs SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, ALERT_TO env vars
python test_connectors.py         # live-network smoke test of every connector (prints count + first 3)
python test_connectors.py "Aon"   # one company, by exact `name` from companies.yaml

docker compose up -d --build      # scheduled runner; secrets in .env (copy .env.example)
docker compose exec job-alerts python main.py --dry-run
```

There is no unit-test suite or linter; `test_connectors.py` hits the real sites.

## Architecture

- `companies.yaml` is a list of company dicts. `platform` selects a connector from the `CONNECTORS` dict in `main.py`; the remaining keys are that connector's config. Optional `keywords` is a case-insensitive substring filter on job titles, applied in `main.py` (not in connectors). No company uses it right now; the user wants to see every role.
- Each connector in `connectors/` exposes `fetch_jobs(company_cfg) -> list[dict]`, returning dicts with `id`, `title`, `url`, `locations` (list of strings, country included when the source has it), `posted` (raw string). `id` must be stable across runs — it is what `state.json` stores (per company name → `{id: ISO date last fetched}`; `load_state` converts the older plain-list format). Adding a new platform means a new connector module plus registering it in `CONNECTORS` in `main.py`.
- `jobformat.py` normalizes those raw strings for the email. `parse_location` classifies each location as US, non-US, or unknown, and renders US ones as "City, ST". `format_posted` renders dates as "Sep 25, 2026". It's a root-level module, so the `Dockerfile` must `COPY` it alongside `main.py`.
- Connectors: `workday` (JSON POST endpoint; currently no company uses it), `attract_api` (iCIMS-backed `/api/jobs`, shared by Aon and First Citizens), `html_scrape` (generic link scraper with `page_param`/`offset_param`/`none` pagination, an optional `link_pattern` regex, and optional `card_selector`/`location_selector`/`posted_selector` CSS selectors that read location and date from each job's listing card), `marsh_phenom` (one specific Phenom `/widgets` payload for careers.marsh.com).
- `state.json` is keyed by company `name`, so renaming a company in `companies.yaml` re-seeds its baseline.

## Behaviors that aren't obvious

- **First run per company seeds a baseline**: if `name` isn't in `state.json`, its postings are recorded but not reported as new.
- **Connector errors are isolated**: a failing company is logged to stderr and its state is left untouched. The run still exits non-zero at the end (even with no new postings, after any email is sent), and the workflow's commit step runs on success or failure (not cancellation), so state is saved and a broken connector shows up as a failed run.
- **Only US postings are kept**: `main.py` drops a posting (from both the email and `state.json`) only when none of its locations is US and at least one is recognizably non-US. Postings with a missing or unparseable location are kept, so a broken `location_selector` shows up as "Location not listed" instead of hiding jobs. Postings are also de-duplicated by `id` there.
- **Empty results are treated as errors**: if a previously-seen company returns zero postings, `main.py` reports a fetch error and keeps its old state rather than wiping it.
- **State is saved only after the email sends**, so an SMTP failure retries the same postings next run instead of losing them.
- **State remembers postings for `SEEN_RETENTION_DAYS` (30) after they were last fetched**: an id missing from a fetch isn't forgotten right away, so it isn't re-reported when it comes back. This matters because fetches are not reliably complete: Aon's `sortBy=relevance` paging skips and duplicates ~1% of jobs per pass (a different ~1% each time), Marsh's order shifts a little between pages, and a truncated `html_scrape` drops ids. Before this window existed, those long-open postings kept reappearing in the email with months-old posted dates. A posting absent for longer than 30 days is reported as new again.
- `html_scrape` uses the full listing-page URL as the job `id`, and its default link regex requires ≥3 hyphenated words in a `/job(s)/` path to avoid nav links; sites with other URL shapes need `link_pattern`.
- `marsh_phenom`: `ddoKey` must be `refineSearch`. The page's initial `eagerLoadRefineSearch` ignores `from` and returns the same first page for every offset, which once made the email repeat the same few roles over and over.
- The Docker schedule is `CRON_SCHEDULE` (default `0 7 * * *`) interpreted in `TZ` (default `America/New_York`), so it tracks DST. The crontab is generated at container start by the `command:` in `compose.yaml` — there's intentionally no committed crontab/shell script, since `core.autocrlf=true` checkouts would add CRLFs.
- The container runs `main.py` from the image, so code/connector changes need `docker compose up -d --build`; `companies.yaml` changes don't.
