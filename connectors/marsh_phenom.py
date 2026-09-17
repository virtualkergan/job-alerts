"""
Connector for careers.marsh.com (Marsh McLennan Agency), a Phenom People
site where the job data genuinely only exists after JavaScript runs -
confirmed by checking the raw page HTML directly (it contains literal
un-rendered template text like "${pageStateData.searchKeyword}"). So
this can't be scraped like WTW/Fidelity; it needs the real API call.

Found by driving an actual browser (Chrome + network inspection) rather
than guessing: the page's own JS calls this endpoint to populate results.

    POST {base_url}/widgets?from={offset}&s=1&rk={rk}
    body: a fairly verbose JSON payload (see BASE_PAYLOAD below) where
    the two fields that matter for us are:
      - "from": pagination offset - MUST also appear in the URL's query
        string, not just the body, or the server silently ignores it and
        always returns page 1 (this cost real time to figure out).
      - "selected_fields": {"business": [...]} - the actual business-unit
        filter, i.e. how we get *only* Marsh McLennan Agency postings
        directly from the server, rather than pattern-matching titles
        after the fact.

Response shape: {"eagerLoadRefineSearch": {"totalHits": N, "data": {"jobs": [...]}}}
"""
import requests

USER_AGENT = "Mozilla/5.0 (compatible; job-alert-bot/1.0)"

BASE_PAYLOAD = {
    "lang": "en_global",
    "deviceType": "desktop",
    "country": "global",
    "irs": False,
    "jobs": True,
    "counts": True,
    "all_fields": [
        "category", "country", "state", "city", "timeType", "business",
        "workFromHome", "campus", "jobType", "phLocSlider", "businessSegmentDescr",
    ],
    "pageType": "landingPage",
    "clearAll": False,
    "jdsource": "facets",
    "isSliderEnable": True,
    "siteType": "external",
    "keywords": "",
    "global": True,
    "locationData": {"sliderRadius": 25, "aboveMaxRadius": False, "LocationUnit": "miles"},
    "rkstatus": True,
    "s": "1",
}


def fetch_jobs(company_cfg: dict, max_pages: int = 30) -> list[dict]:
    base_url = company_cfg["base_url"].rstrip("/")
    rk = company_cfg["rk"]
    page_name = company_cfg["page_name"]
    page_id = company_cfg["page_id"]
    business_filter = company_cfg.get("business_filter", [])
    size = company_cfg.get("size", 50)

    api_url = f"{base_url}/widgets"
    jobs = []

    for page in range(max_pages):
        offset = page * size
        payload = dict(
            BASE_PAYLOAD,
            pageName=page_name,
            ddoKey="eagerLoadRefineSearch",
            subsearch="",
            size=size,
            rk=rk,
            pageId=page_id,
            selected_fields={"business": business_filter} if business_filter else {},
        )
        payload["from"] = offset

        resp = requests.post(
            api_url,
            params={"from": offset, "s": "1", "rk": rk},  # "from" MUST be in the URL too
            json=payload,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json().get("eagerLoadRefineSearch", {})
        postings = data.get("data", {}).get("jobs", [])
        if not postings:
            break

        for p in postings:
            jobs.append(
                {
                    "id": p.get("reqId") or p.get("jobId", ""),
                    "title": p.get("title", "Untitled role"),
                    "url": p.get("applyUrl", ""),
                    "location": p.get("location", ""),
                    "posted": p.get("postedDate", ""),
                }
            )

        total = data.get("totalHits", 0)
        if len(jobs) >= total:
            break

    return jobs
