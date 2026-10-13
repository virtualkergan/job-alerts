"""
Connector for a career-site platform (backed by iCIMS) that a number of
large employers use, identified by a consistent, well-formed JSON API:

    GET {base_url}/api/jobs?page={n}&sortBy=relevance&descending=false&internal=false

Confirmed working for both First Citizens Bank (jobs.firstcitizens.com)
and Aon (jobs.aon.com) - same response shape, different base_url. Any
other company found to use this same API only needs a companies.yaml
entry with platform "attract_api" and its base_url; no new code.
"""
import requests

USER_AGENT = "Mozilla/5.0 (compatible; job-alert-bot/1.0)"


def _locations(d: dict) -> list[str]:
    """Primary location plus any additional_locations, each as
    "City, State, Country" so the country is always explicit."""
    locations = []
    for loc in [d] + (d.get("additional_locations") or []):
        text = ", ".join(loc[k] for k in ("city", "state", "country") if loc.get(k))
        if text and text not in locations:
            locations.append(text)
    if not locations and d.get("short_location"):
        locations.append(d["short_location"])
    return locations


def fetch_jobs(company_cfg: dict, max_pages: int = 300) -> list[dict]:
    base_url = company_cfg["base_url"].rstrip("/")
    api_url = f"{base_url}/api/jobs"
    jobs = []

    for page in range(1, max_pages + 1):
        params = {
            "page": page,
            "sortBy": "relevance",
            "descending": "false",
            "internal": "false",
        }
        resp = requests.get(
            api_url, params=params, headers={"User-Agent": USER_AGENT}, timeout=20
        )
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("jobs", [])
        if not postings:
            break

        for entry in postings:
            d = entry.get("data", {})
            jobs.append(
                {
                    "id": d.get("req_id") or d.get("slug", ""),
                    "title": d.get("title", "Untitled role"),
                    "url": d.get("canonical_url") or d.get("apply_url", ""),
                    "locations": _locations(d),
                    "posted": d.get("posted_date", ""),
                    # The posting pages sit behind a bot check, but the API
                    # already has the full text; summary.py reads it from here.
                    "description": d.get("description", ""),
                }
            )

    return jobs
