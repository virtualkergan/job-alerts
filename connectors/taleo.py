"""
Connector for Taleo "careersection" job boards, e.g.
    https://cinfin.taleo.net/careersection/ex/jobsearch.ftl?lang=en
Confirmed for Cincinnati Insurance.

The search page loads its results from a JSON endpoint:
    POST https://{tenant}.taleo.net/careersection/rest/jobboard/searchjobs?lang=en&portal={portal}
The portal number is embedded in jobsearch.ftl's HTML (search it for
"portal"). Each requisition's "column" list is configured per site; on
Cincinnati's board it is [req number, title, '["ST-City", ...]'], and
"linkedColumn" / "locationsColumns" say which entries are the title and
locations. There's no posted date in the listing.
"""
import json
import re

import requests

USER_AGENT = "Mozilla/5.0 (compatible; job-alert-bot/1.0)"
# Taleo writes locations as "OH-Fairfield"; turn those into "Fairfield, OH".
STATE_CITY_RE = re.compile(r"^([A-Z]{2})-(.+)$")


def _locations(raw: str) -> list[str]:
    try:
        values = json.loads(raw)
    except (TypeError, ValueError):
        values = [raw] if raw else []
    locations = []
    for v in values:
        m = STATE_CITY_RE.match(v.strip())
        locations.append(f"{m.group(2)}, {m.group(1)}" if m else v.strip())
    return locations


def fetch_jobs(company_cfg: dict, max_pages: int = 100) -> list[dict]:
    tenant = company_cfg["tenant"]
    section = company_cfg["section"]
    base = f"https://{tenant}.taleo.net/careersection"
    api_url = f"{base}/rest/jobboard/searchjobs"

    jobs = []
    for page in range(1, max_pages + 1):
        body = {
            "multilineEnabled": False,
            "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
            "fieldData": {"fields": {"KEYWORD": "", "LOCATION": ""}, "valid": True},
            "filterSelectionParam": {"searchFilterSelections": []},
            "advancedSearchFiltersSelectionParam": {"searchFilterSelections": []},
            "pageNo": page,
        }
        resp = requests.post(
            api_url,
            params={"lang": "en", "portal": company_cfg["portal"]},
            json=body,
            # Taleo answers 500 without the timezone headers its own page sends.
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
                "tz": "GMT-04:00",
                "tzname": "America/New_York",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("requisitionList", [])
        if not postings:
            break

        for p in postings:
            cols = p.get("column", [])
            title_idx = p.get("linkedColumn", 1)
            loc_idxs = p.get("locationsColumns", [])
            jobs.append(
                {
                    "id": p["jobId"],
                    "title": (cols[title_idx] if title_idx < len(cols) else "").strip() or "Untitled role",
                    "url": f"{base}/{section}/jobdetail.ftl?job={p['jobId']}&lang=en",
                    "locations": [loc for i in loc_idxs if i < len(cols) for loc in _locations(cols[i])],
                    "posted": "",
                }
            )

        if len(jobs) >= data.get("pagingData", {}).get("totalCount", 0):
            break

    return jobs
