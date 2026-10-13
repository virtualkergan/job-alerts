"""
Picks the day's best-fit postings for the "Top matches" section of the email,
by asking Claude to compare the new postings against resume.pdf.

Two stages, because connectors only collect titles, not descriptions:
  1. Shortlist from titles alone (one line per posting).
  2. Fetch each shortlisted posting's page for its description, then have
     Claude pick and rank the final ten with a one-line reason each.

The feature is opt-in: with no resume.pdf next to this file, pick_top_jobs
returns nothing and the email is sent as before.

Try it against one company's live postings:  python summary.py "Aon"
"""
import base64
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote

import anthropic
import requests
from bs4 import BeautifulSoup

from connectors.html_scrape import BROWSER_HEADERS
from jobformat import format_locations

RESUME_FILE = Path(__file__).parent / "resume.pdf"

MODEL = "claude-sonnet-5-5"
TOP_N = 10
SHORTLIST_SIZE = 25
# Per-posting cap on description text sent to Claude; the requirements and
# qualifications sections of a posting sit well inside this.
MAX_DESCRIPTION_CHARS = 12000
# Shorter than this is a cookie banner or a JavaScript shell, not a description.
MIN_DESCRIPTION_CHARS = 200
MIN_EMBEDDED_CHARS = 1000
_EMBEDDED_DESCRIPTION_RE = re.compile(
    r'"(?:[Dd]escription|ExternalDescriptionStr)"\s*:\s*("(?:[^"\\]|\\.)*")'
)

CRITERIA = """\
You are screening job postings for the candidate whose resume is attached.

Only these kinds of roles qualify:
- actuarial (actuarial analyst/assistant/associate, pricing, reserving, valuation, actuarial rotational or development programs)
- underwriting (underwriter trainee, assistant/associate underwriter, underwriting analyst or assistant)
- closely related risk management work (risk analyst, catastrophe or exposure modeling, insurance or reinsurance analytics)

They must also be entry level: roughly 0-3 years of experience, typically titled analyst, associate, assistant, trainee, or level I, including new-graduate and rotational programs. Internships count only if the resume shows the candidate is still a student. Exclude senior, lead, principal, manager, director and VP roles, and roles that require a credential the candidate does not hold (ASA, FSA, ACAS, FCAS, CPCU and similar).

Among qualifying roles, prefer the ones the candidate's education, exam progress, skills and experience fit best."""

SHORTLIST_PROMPT = """\
Below are today's new postings, one per line as: number | company | title | locations.

You only have titles at this stage; the full descriptions of your picks are read in a second pass. Return the numbers of up to {limit} postings that could plausibly qualify, most promising first. Keep a posting whose title is ambiguous about seniority, and leave out anything clearly outside the qualifying kinds of role or clearly senior. Return an empty list if nothing qualifies.

{postings}"""

FINAL_PROMPT = """\
Below are the shortlisted postings with their descriptions. Where a description could not be retrieved, judge the posting on its title and company alone and be more cautious about it.

Return up to {limit} postings that qualify, best fit first. Return fewer when fewer qualify, and an empty list when none do, instead of filling the list with poor fits. For each, give a one-sentence reason addressed to the candidate ("you"), naming the specific thing in their background that matches what the posting asks for.

{postings}"""

SHORTLIST_SCHEMA = {
    "type": "object",
    "properties": {"shortlist": {"type": "array", "items": {"type": "integer"}}},
    "required": ["shortlist"],
    "additionalProperties": False,
}

FINAL_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"number": {"type": "integer"}, "reason": {"type": "string"}},
                "required": ["number", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["picks"],
    "additionalProperties": False,
}


def _ask_claude(client: anthropic.Anthropic, resume_b64: str, prompt: str, schema: dict) -> dict:
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=CRITERIA,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
        # If the model's safety classifiers decline the request, the API
        # re-runs it on Anthropic's recommended fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": resume_b64},
                    # Both stages start with the same resume, so stage 2 reads it from cache.
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": prompt},
            ],
        }],
    )
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"Claude stopped with {response.stop_reason} instead of answering")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def _valid_numbers(numbers: list[int], count: int, limit: int) -> list[int]:
    """Drops repeats and numbers that don't refer to a posting."""
    return [n for n in dict.fromkeys(numbers) if 1 <= n <= count][:limit]


def _find_job_posting(node) -> dict | None:
    """Finds the schema.org JobPosting in a JSON-LD value (it may be nested in a list or @graph)."""
    if isinstance(node, list):
        return next((found for item in node if (found := _find_job_posting(item))), None)
    if not isinstance(node, dict):
        return None
    types = node.get("@type")
    if "JobPosting" in (types if isinstance(types, list) else [types]):
        return node
    return _find_job_posting(node.get("@graph"))


def _html_to_text(markup: str) -> str:
    return BeautifulSoup(markup, "html.parser").get_text(" ", strip=True)


def _embedded_description(raw: str) -> str:
    """The longest description-like JSON string value in raw, which is either
    a JSON API response (Oracle) or a page with its data inlined in a script (UKG)."""
    # Taleo inlines the posting as URL-encoded fields separated by "!|!"
    # ([1:-1] drops the page markup before the first and after the last field).
    best = unquote(max(raw.split("!|!")[1:-1], key=len, default=""))
    for match in _EMBEDDED_DESCRIPTION_RE.finditer(raw):
        try:
            value = json.loads(match.group(1))
        except ValueError:
            continue
        best = max(best, value, key=len)
    text = _html_to_text(best)
    # Pages also carry short "description" strings (cookie notices, SEO blurbs).
    return text if len(text) >= MIN_EMBEDDED_CHARS else ""


def fetch_description(job: dict) -> str:
    """Returns the posting's description text, or "" if it can't be read."""
    # Connectors whose listing API includes the description pass it along.
    text = _html_to_text(job.get("description") or "")
    if len(text) < MIN_DESCRIPTION_CHARS:
        try:
            resp = requests.get(job.get("description_url") or job["url"], headers=BROWSER_HEADERS, timeout=20)
            resp.raise_for_status()
        except requests.RequestException:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")

        # Most career sites embed the description as JSON-LD for search engines,
        # even when the visible page is rendered by JavaScript.
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                posting = _find_job_posting(json.loads(script.string or ""))
            except ValueError:
                continue
            if posting and isinstance(posting.get("description"), str):
                text = _html_to_text(posting["description"])
                break
        if len(text) < MIN_DESCRIPTION_CHARS:
            text = _embedded_description(resp.text)
        if len(text) < MIN_DESCRIPTION_CHARS:
            for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
                tag.decompose()
            body = soup.find("main") or soup.body or soup
            text = body.get_text(" ", strip=True)
    if len(text) < MIN_DESCRIPTION_CHARS:
        return ""
    return text[:MAX_DESCRIPTION_CHARS]


def pick_top_jobs(results: dict[str, list[dict]]) -> list[dict]:
    """Returns up to TOP_N {"company", "job", "reason"} dicts, best fit first."""
    # is_file, not exists: Docker creates a directory when a bind-mounted file is missing.
    if not RESUME_FILE.is_file():
        return []
    postings = [(company, job) for company, jobs in results.items() for job in jobs]
    if not postings:
        return []

    resume_b64 = base64.standard_b64encode(RESUME_FILE.read_bytes()).decode("ascii")
    client = anthropic.Anthropic()

    # Claude refers to postings by number, so it can't return a made-up id or URL.
    if len(postings) > SHORTLIST_SIZE:
        lines = "\n".join(
            f"{n} | {company} | {' '.join(job['title'].split())} | {format_locations(job.get('locations', []))}"
            for n, (company, job) in enumerate(postings, 1)
        )
        answer = _ask_claude(
            client, resume_b64,
            SHORTLIST_PROMPT.format(limit=SHORTLIST_SIZE, postings=lines),
            SHORTLIST_SCHEMA,
        )
        shortlist = [postings[n - 1] for n in _valid_numbers(answer["shortlist"], len(postings), SHORTLIST_SIZE)]
    else:
        shortlist = postings
    if not shortlist:
        return []

    with ThreadPoolExecutor(max_workers=5) as pool:
        descriptions = list(pool.map(fetch_description, [job for _, job in shortlist]))
    found = sum(1 for d in descriptions if d)
    print(f"[summary] {len(postings)} new postings, {len(shortlist)} shortlisted, {found} descriptions retrieved")

    blocks = "\n\n".join(
        f"<posting number=\"{n}\">\n"
        f"Company: {company}\n"
        f"Title: {' '.join(job['title'].split())}\n"
        f"Locations: {format_locations(job.get('locations', []))}\n"
        f"Description: {description or '(could not be retrieved)'}\n"
        "</posting>"
        for n, ((company, job), description) in enumerate(zip(shortlist, descriptions), 1)
    )
    answer = _ask_claude(
        client, resume_b64,
        FINAL_PROMPT.format(limit=TOP_N, postings=blocks),
        FINAL_SCHEMA,
    )
    reasons = {p["number"]: p["reason"] for p in reversed(answer["picks"])}
    numbers = _valid_numbers([p["number"] for p in answer["picks"]], len(shortlist), TOP_N)
    return [
        {"company": shortlist[n - 1][0], "job": shortlist[n - 1][1], "reason": reasons[n]}
        for n in numbers
    ]


if __name__ == "__main__":
    from jobformat import is_us_job
    from main import CONNECTORS, load_companies

    if len(sys.argv) != 2:
        sys.exit('usage: python summary.py "Company Name"')
    if not RESUME_FILE.is_file():
        sys.exit(f"{RESUME_FILE} not found")
    company = next((c for c in load_companies() if c["name"] == sys.argv[1]), None)
    if company is None:
        sys.exit(f"no company named {sys.argv[1]!r} in companies.yaml")

    jobs = [j for j in CONNECTORS[company["platform"]](company) if is_us_job(j)]
    top = pick_top_jobs({company["name"]: jobs})
    if not top:
        print("No qualifying postings.")
    for rank, pick in enumerate(top, 1):
        job = pick["job"]
        print(f"\n{rank}. {job['title']}  ->  {job['url']}")
        print(f"   {format_locations(job.get('locations', []))}")
        print(f"   {pick['reason']}")
