"""
Generic connector for career sites that render their job search results
as plain HTML (no JavaScript needed to see the listings) - confirmed to
work for WTW's careers.wtwco.com/jobs/search and Fidelity's jobs.fidelity.com.

Strategy: fetch the listing page (and subsequent ?page=N pages), find
every link whose path looks like an individual job posting, and use the
link text as the title. This makes no assumption about which ATS is
behind the scenes - it just reads what a browser would show you.
"""
import re
import time
import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# A job-posting link on these kinds of sites is reliably distinguishable
# from nav/footer links because real job slugs are long and hyphenated
# ("wellbeing-equity-and-disability-management-..."), unlike nav paths
# such as "/jobs/search" or "/jobs/saved-jobs" which are short and generic.
# Requiring at least 3 hyphen-separated words filters those out. Override
# per-company with a "link_pattern" key in companies.yaml when a site's
# URLs don't follow this shape (e.g. Avature's "/JobDetail/...").
DEFAULT_JOB_LINK_RE = re.compile(r"/jobs?/[a-z0-9]+(?:-[a-z0-9]+){2,}", re.IGNORECASE)

# Fidelity lists several locations in one element, e.g.
# "Westlake, TX / Merrimack, NH / Durham, NC + 1 Other Location".
MULTI_LOCATION_SEP_RE = re.compile(r"\s+/\s+")
OTHER_LOCATIONS_RE = re.compile(r"\s*\+\s*\d+\s+Other Locations?\s*$", re.IGNORECASE)


def _card_details(card, location_selector: str | None, posted_selector: str | None) -> tuple[list[str], str]:
    """Pull locations and posted date out of the element wrapping one job."""
    locations = []
    if card is not None and location_selector:
        for el in card.select(location_selector):
            text = OTHER_LOCATIONS_RE.sub("", el.get_text(" ", strip=True))
            locations.extend(loc for loc in MULTI_LOCATION_SEP_RE.split(text) if loc)
    posted = ""
    if card is not None and posted_selector:
        el = card.select_one(posted_selector)
        posted = el.get_text(" ", strip=True) if el else ""
    return locations, posted


def fetch_jobs(company_cfg: dict, max_pages: int = 60) -> list[dict]:
    listing_url = company_cfg["listing_url"]
    # pagination styles:
    #   "page_param"   -> appends ?page=N (or &page=N if url already has a query)
    #   "offset_param" -> appends an incrementing offset param (Avature-style,
    #                      e.g. &jobOffset=50, &jobOffset=100 ...) using
    #                      "offset_param_name" and "per_page" from the config
    #   "none"         -> single page only, no pagination
    pagination = company_cfg.get("pagination", "page_param")
    offset_param_name = company_cfg.get("offset_param_name", "jobOffset")
    per_page = company_cfg.get("per_page", 50)
    job_link_re = (
        re.compile(company_cfg["link_pattern"], re.IGNORECASE)
        if company_cfg.get("link_pattern")
        else DEFAULT_JOB_LINK_RE
    )
    # Optional CSS selectors for location/date: "card_selector" matches the
    # element wrapping one job (table row, card div, ...); the other two are
    # looked up inside that card.
    card_selector = company_cfg.get("card_selector")
    location_selector = company_cfg.get("location_selector")
    posted_selector = company_cfg.get("posted_selector")
    # Optional CSS selector limiting which links are considered at all, for
    # pages whose job links have no recognizable URL shape (NCRB's openings
    # are hand-placed links in one CMS content block).
    link_selector = company_cfg.get("link_selector", "a[href]")
    seen_urls = set()
    jobs = []
    consecutive_empty_pages = 0

    # A real Session (not a fresh request each time) carries cookies from
    # page to page, the way a browser naturally would. Several enterprise
    # sites (WTW included) allow a first, cookie-less request through but
    # throttle or reject subsequent ones without a session - a stateless
    # client looks far more bot-like than one that behaves like a browser
    # walking through search results page by page.
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    referer = None

    for page in range(1, max_pages + 1):
        if page > 1 and pagination == "none":
            break

        if page == 1:
            url = listing_url
        elif pagination == "offset_param":
            sep = "&" if "?" in listing_url else "?"
            url = f"{listing_url}{sep}{offset_param_name}={(page - 1) * per_page}"
        else:
            sep = "&" if "?" in listing_url else "?"
            url = f"{listing_url}{sep}page={page}"

        headers = {"Referer": referer} if referer else {}

        resp = None
        for attempt in range(3):
            try:
                resp = session.get(url, headers=headers, timeout=20)
                if resp.status_code == 200:
                    break
            except requests.RequestException:
                resp = None
            time.sleep(1.5 * (attempt + 1))  # back off before retrying

        if resp is None or resp.status_code != 200:
            break  # genuinely unreachable after retries; stop here

        referer = url
        if page > 1:
            time.sleep(0.75)  # small courtesy delay between page requests

        soup = BeautifulSoup(resp.text, "html.parser")
        card_ids = {id(c) for c in soup.select(card_selector)} if card_selector else set()

        links_found_on_page = 0
        for a in soup.select(link_selector):
            href = a.get("href", "")
            if not job_link_re.search(href):
                continue
            links_found_on_page += 1
            full_url = href if href.startswith("http") else requests.compat.urljoin(url, href)
            if full_url in seen_urls:
                continue
            title = a.get_text(strip=True)
            if not title:
                continue
            seen_urls.add(full_url)
            card = next((p for p in a.parents if id(p) in card_ids), None)
            locations, posted = _card_details(card, location_selector, posted_selector)
            jobs.append({"id": full_url, "title": title, "url": full_url, "locations": locations, "posted": posted})

        # Stop once we hit two genuinely EMPTY pages in a row (no job links
        # at all - a real sign we've run past the last page). A page whose
        # links are all duplicates of ones we've already seen does NOT
        # count as empty here: search-results sort order can shift slightly
        # between page requests (e.g. a job posted mid-scrape bumping
        # others down), which can otherwise cause a false "no new jobs on
        # this page" and stop the scrape early, well short of the real end.
        if links_found_on_page == 0:
            consecutive_empty_pages += 1
            if consecutive_empty_pages >= 2:
                break
        else:
            consecutive_empty_pages = 0

    return jobs
