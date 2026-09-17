"""
Connector for companies that host their career site on Workday.

Every Workday career site (things like {tenant}.wd{N}.myworkdayjobs.com)
exposes a JSON search endpoint that the page itself calls in the browser.
It's not an "official public API" with a key, but it's the same request
your browser makes, and Workday doesn't rate-limit or block it for
reasonable, low-frequency use like one check per day.

Endpoint shape:
    POST https://{tenant}.{wd_number}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
"""
import requests

USER_AGENT = "Mozilla/5.0 (compatible; job-alert-bot/1.0)"


def fetch_jobs(company_cfg: dict, max_pages: int = 50) -> list[dict]:
    tenant = company_cfg["tenant"]
    wd_number = company_cfg["wd_number"]
    site = company_cfg["site"]

    base = f"https://{tenant}.{wd_number}.myworkdayjobs.com"
    api_url = f"{base}/wday/cxs/{tenant}/{site}/jobs"

    jobs = []
    limit = 20
    for page in range(max_pages):
        payload = {
            "appliedFacets": {},
            "limit": limit,
            "offset": page * limit,
            "searchText": "",
        }
        resp = requests.post(
            api_url,
            json=payload,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("jobPostings", [])
        if not postings:
            break

        for p in postings:
            external_path = p.get("externalPath", "")
            jobs.append(
                {
                    "id": external_path,  # stable per-job identifier
                    "title": p.get("title", "Untitled role"),
                    "url": f"{base}/{site}{external_path}",
                    "location": p.get("locationsText", ""),
                    "posted": p.get("postedOn", ""),
                }
            )

        total = data.get("total", 0)
        if len(jobs) >= total:
            break

    return jobs
