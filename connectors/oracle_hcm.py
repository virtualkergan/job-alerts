"""
Connector for career sites on Oracle Recruiting Cloud (Oracle HCM
"Candidate Experience"), recognizable by URLs like
    https://{host}.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/{site}
Confirmed for Westfield (site "Careers"), Chubb ("CX_2001") and Verisk ("CX_1").

The page loads its results from this public REST endpoint:
    GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
        ?onlyData=true&expand=requisitionList.secondaryLocations
        &finder=findReqs;siteNumber={site},limit=25,offset=N,sortBy=POSTING_DATES_DESC

Response: {"items": [{"TotalJobsCount": N, "requisitionList": [...]}]}
"""
import requests

USER_AGENT = "Mozilla/5.0 (compatible; job-alert-bot/1.0)"
PAGE_SIZE = 25


def fetch_jobs(company_cfg: dict, max_pages: int = 200) -> list[dict]:
    host = company_cfg["host"]
    site = company_cfg["site"]
    api_url = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"

    jobs = []
    for page in range(max_pages):
        params = {
            "onlyData": "true",
            "expand": "requisitionList.secondaryLocations",
            "finder": (
                f"findReqs;siteNumber={site},limit={PAGE_SIZE},"
                f"offset={page * PAGE_SIZE},sortBy=POSTING_DATES_DESC"
            ),
        }
        resp = requests.get(api_url, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        result = resp.json()["items"][0]
        postings = result.get("requisitionList", [])
        if not postings:
            break

        for p in postings:
            # Locations come as "City, ST, United States", so the country is explicit.
            locations = [p["PrimaryLocation"]] if p.get("PrimaryLocation") else []
            locations += [s["Name"] for s in p.get("secondaryLocations") or [] if s.get("Name")]
            jobs.append(
                {
                    "id": p["Id"],
                    "title": p.get("Title", "Untitled role"),
                    "url": f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{p['Id']}",
                    "locations": locations,
                    "posted": p.get("PostedDate", ""),
                }
            )

        if len(jobs) >= result.get("TotalJobsCount", 0):
            break

    return jobs
