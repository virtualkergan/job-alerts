"""
Connector for companies that host their career site on Workday.

Every Workday career site (things like {tenant}.wd{N}.myworkdayjobs.com)
exposes a JSON search endpoint that the page itself calls in the browser.
It's not an "official public API" with a key, but it's the same request
your browser makes, and Workday doesn't rate-limit or block it for
reasonable, low-frequency use like one check per day.

Endpoint shape:
    POST https://{tenant}.{wd_number}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs

locationsText is either one location ("Northbrook, IL") or a count
("3 Locations"); the count can't be classified, so those postings are kept.
"""
import requests

USER_AGENT = "Mozilla/5.0 (compatible; job-alert-bot/1.0)"


def _country_facet(api_url: str, country: str) -> dict:
    """Finds the site's country facet (its name varies: "Country",
    "locationCountry", sometimes nested under a location group) and returns
    {facet name: [id of `country`]}, ready for appliedFacets."""
    resp = requests.post(
        api_url,
        json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    facets = resp.json().get("facets", [])
    while facets:
        f = facets.pop()
        values = f.get("values", [])
        if "country" in f.get("facetParameter", "").lower():
            for v in values:
                if v.get("descriptor") == country:
                    return {f["facetParameter"]: [v["id"]]}
        facets.extend(v for v in values if "facetParameter" in v)
    raise ValueError(f"no country facet value {country!r} on {api_url}")


def fetch_jobs(company_cfg: dict, max_pages: int = 50) -> list[dict]:
    tenant = company_cfg["tenant"]
    wd_number = company_cfg["wd_number"]
    site = company_cfg["site"]

    base = f"https://{tenant}.{wd_number}.myworkdayjobs.com"
    api_url = f"{base}/wday/cxs/{tenant}/{site}/jobs"

    # Optional server-side filter, copied from the site's own URL query,
    # e.g. {"hiringCompany": ["4c55..."]} for one NC state agency.
    applied_facets = dict(company_cfg.get("applied_facets", {}))
    # Optional country filter by name ("United States of America"). Workday's
    # locationsText has no country ("Ind - Pune ...", "3 Locations"), so
    # without this, non-US postings can't be told apart and get kept.
    if company_cfg.get("country"):
        applied_facets.update(_country_facet(api_url, company_cfg["country"]))

    jobs = []
    limit = 20
    total = 0
    for page in range(max_pages):
        payload = {
            "appliedFacets": applied_facets,
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
                    "locations": [p["locationsText"]] if p.get("locationsText") else [],
                    "posted": p.get("postedOn", ""),
                }
            )

        # Workday reports the real total only on the first page; later pages say 0.
        total = total or data.get("total", 0)
        if len(jobs) >= total:
            break

    return jobs
