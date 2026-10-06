"""
Connector for Eightfold AI career sites, e.g.
    https://searchjobs.libertymutualgroup.com/careers
Confirmed for Liberty Mutual.

The page loads its results from:
    GET {base_url}/api/apply/v2/jobs?domain={domain}&start=N&num=10&sort_by=timestamp
Response: {"count": N, "positions": [...]}; the API returns at most 10 per page.
"""
from datetime import datetime, timezone

import requests

USER_AGENT = "Mozilla/5.0 (compatible; job-alert-bot/1.0)"
PAGE_SIZE = 10


def fetch_jobs(company_cfg: dict, max_pages: int = 300) -> list[dict]:
    base_url = company_cfg["base_url"].rstrip("/")
    api_url = f"{base_url}/api/apply/v2/jobs"

    jobs = []
    for page in range(max_pages):
        params = {
            "domain": company_cfg["domain"],
            "start": page * PAGE_SIZE,
            "num": PAGE_SIZE,
            "sort_by": "timestamp",
        }
        resp = requests.get(api_url, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("positions", [])
        if not postings:
            break

        for p in postings:
            created = p.get("t_create")
            jobs.append(
                {
                    "id": str(p["id"]),
                    "title": p.get("name", "Untitled role"),
                    "url": p.get("canonicalPositionUrl") or f"{base_url}/careers/job/{p['id']}",
                    "locations": p.get("locations") or [],
                    "posted": datetime.fromtimestamp(created, timezone.utc).date().isoformat() if created else "",
                }
            )

        if len(jobs) >= data.get("count", 0):
            break

    return jobs
