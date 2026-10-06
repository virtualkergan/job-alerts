"""
Connector for UKG Pro (formerly UltiPro) recruiting job boards, e.g.
    https://recruiting2.ultipro.com/HER1001ACFIN/JobBoard/ab33798a-3521-417b-8db8-a8e435c475fa/
Confirmed for Acuity.

The board page loads its results from:
    POST {board_url}JobBoardView/LoadSearchResults
    body: {"opportunitySearch": {"Top": N, "Skip": offset, ...}}
Response: {"opportunities": [...], "totalCount": N}
"""
import requests

USER_AGENT = "Mozilla/5.0 (compatible; job-alert-bot/1.0)"
PAGE_SIZE = 50


def _location(loc: dict) -> str:
    addr = loc.get("Address") or {}
    state = (addr.get("State") or {}).get("Code")
    country = (addr.get("Country") or {}).get("Name")
    parts = [addr.get("City"), state, country]
    if not addr.get("City"):
        parts.insert(0, loc.get("LocalizedName"))  # e.g. "Remote", United States
    return ", ".join(p for p in parts if p)


def fetch_jobs(company_cfg: dict, max_pages: int = 100) -> list[dict]:
    board_url = company_cfg["board_url"].rstrip("/") + "/"
    api_url = f"{board_url}JobBoardView/LoadSearchResults"

    jobs = []
    for page in range(max_pages):
        body = {
            "opportunitySearch": {
                "Top": PAGE_SIZE,
                "Skip": page * PAGE_SIZE,
                "QueryString": "",
                "OrderBy": [{"Value": "postedDateDesc", "PropertyName": "PostedDate", "Ascending": False}],
                "Filters": [],
            }
        }
        resp = requests.post(api_url, json=body, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("opportunities", [])
        if not postings:
            break

        for p in postings:
            jobs.append(
                {
                    "id": p["Id"],
                    "title": p.get("Title", "Untitled role"),
                    "url": f"{board_url}OpportunityDetail?opportunityId={p['Id']}",
                    "locations": [loc for loc in map(_location, p.get("Locations") or []) if loc],
                    "posted": p.get("PostedDate", ""),
                }
            )

        if len(jobs) >= data.get("totalCount", 0):
            break

    return jobs
