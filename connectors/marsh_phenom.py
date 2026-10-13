"""
Connector for careers.marsh.com (Marsh McLennan Agency), a Phenom People
site where the job data genuinely only exists after JavaScript runs -
confirmed by checking the raw page HTML directly (it contains literal
un-rendered template text like "${pageStateData.searchKeyword}"). So
this can't be scraped like WTW/Fidelity; it needs the real API call.

Found by driving an actual browser (Chrome + network inspection) rather
than guessing: the page's own JS calls this endpoint to populate results.

    POST {base_url}/widgets
    body: a fairly verbose JSON payload (see BASE_PAYLOAD below) where
    the fields that matter for us are:
      - "ddoKey": MUST be "refineSearch". The page's first load uses
        "eagerLoadRefineSearch", but that variant ignores "from" and
        returns the same first page for every offset, so paging with it
        collects the same ~50 jobs over and over.
      - "from": pagination offset.
      - "selected_fields": {"business": [...]} - the actual business-unit
        filter, i.e. how we get *only* Marsh McLennan Agency postings
        directly from the server, rather than pattern-matching titles
        after the fact.

Response shape: {"refineSearch": {"totalHits": N, "data": {"jobs": [...]}}}
"""
import requests

USER_AGENT = "Mozilla/5.0 (compatible; job-alert-bot/1.0)"
DDO_KEY = "refineSearch"

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
    seen_ids = set()

    for page in range(max_pages):
        offset = page * size
        payload = dict(
            BASE_PAYLOAD,
            pageName=page_name,
            ddoKey=DDO_KEY,
            subsearch="",
            size=size,
            rk=rk,
            pageId=page_id,
            selected_fields={"business": business_filter} if business_filter else {},
        )
        payload["from"] = offset

        resp = requests.post(
            api_url,
            json=payload,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json().get(DDO_KEY, {})
        postings = data.get("data", {}).get("jobs", [])
        if not postings:
            break

        for p in postings:
            job_id = p.get("reqId") or p.get("jobId", "")
            # Result order can shift slightly between page requests, so the
            # same posting occasionally shows up on two adjacent pages.
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            locations = p.get("multi_location") or [p.get("cityStateCountry", "")]
            jobs.append(
                {
                    "id": job_id,
                    "title": p.get("title", "Untitled role"),
                    # applyUrl is the Workday posting plus "/apply", which opens
                    # the application; without it the link shows the description.
                    "url": p.get("applyUrl", "").removesuffix("/apply"),
                    "locations": [loc for loc in locations if loc],
                    "posted": p.get("postedDate", ""),
                }
            )

        if offset + size >= data.get("totalHits", 0):
            break

    return jobs
