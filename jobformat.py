"""
Shared helpers that turn the loosely-formatted location and date strings
each connector returns into one consistent shape for the email, and decide
whether a posting is US-based.

Location strings seen in the wild (all handled by parse_location):
    "Chicago, Illinois, United States"                       (Aon, WTW)
    "3300 West Esplanade Ave, Metairie, LA 70002, United States of America"  (Marsh)
    "Durham, NC"                                             (Fidelity)
    "Tokyo, Japan" / "Toronto, Ontario, Canada"              (non-US)
    "Remote" / ""                                            (unknown)
"""
import re
from datetime import date, datetime

US_STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Puerto Rico": "PR", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}
_STATE_BY_NAME = {name.lower(): abbr for name, abbr in US_STATES.items()}
_STATE_ABBRS = set(US_STATES.values())
_US_COUNTRY_NAMES = {"united states", "united states of america", "usa", "us", "u.s.", "u.s.a."}
_ZIP_RE = re.compile(r"\s+\d{5}(?:-\d{4})?$")


def _state_abbr(text: str) -> str | None:
    if text in _STATE_ABBRS:  # case-sensitive: "IN" is Indiana, "in" is not
        return text
    return _STATE_BY_NAME.get(text.lower())


def _us_display(parts: list[str]) -> str:
    """parts = the location's comma-separated pieces with the country removed."""
    if not parts:
        return "United States"
    state = _state_abbr(parts[-1])
    if state is None:
        return ", ".join(parts + ["US"])  # "Remote, United States" -> "Remote, US"
    return f"{parts[-2]}, {state}" if len(parts) >= 2 else state


def parse_location(text: str) -> tuple[str, str | None]:
    """Returns (display_text, kind) where kind is "us", "non_us", or None if unknown."""
    parts = [_ZIP_RE.sub("", p.strip()) for p in (text or "").split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return "", None
    if parts[-1].lower() in _US_COUNTRY_NAMES:
        return _us_display(parts[:-1]), "us"
    if _state_abbr(parts[-1]):
        return _us_display(parts), "us"
    if len(parts) >= 2:
        # "City, Country" or "City, Region, Country" with a non-US country.
        return f"{parts[0]}, {parts[-1]}", "non_us"
    return parts[0], None  # "Remote", "Multiple Locations", ...


def is_us_job(job: dict) -> bool:
    """True if any location is in the US, or if no location is known to be
    outside it - a posting with unparseable/missing location is kept rather
    than silently dropped."""
    kinds = [parse_location(loc)[1] for loc in job.get("locations", [])]
    return "us" in kinds or "non_us" not in kinds


def format_locations(locations: list[str], max_shown: int = 2) -> str:
    parsed = [parse_location(loc) for loc in locations]
    us = [display for display, kind in parsed if kind == "us"]
    candidates = us or [display for display, _ in parsed if display]
    shown = list(dict.fromkeys(candidates))  # de-dupe (e.g. two offices in one city)
    if not shown:
        return "Location not listed"
    text = "; ".join(shown[:max_shown])
    if len(shown) > max_shown:
        text += f" +{len(shown) - max_shown} more"
    return text


def parse_posted(text: str, today: date | None = None) -> date | None:
    text = (text or "").strip()
    if text.lower().startswith("posted "):
        text = text[len("posted "):].strip()
    if not text:
        return None
    if re.match(r"\d{4}-\d{2}-\d{2}", text):  # ISO, e.g. 2026-09-25T08:40:00+0000
        return date.fromisoformat(text[:10])
    for fmt in ("%d-%b-%Y", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    # Year-less "Sep 25" (Fidelity): assume the most recent such date.
    today = today or date.today()
    for fmt in ("%b %d", "%B %d"):
        try:
            d = datetime.strptime(f"{text} {today.year}", f"{fmt} %Y").date()
        except ValueError:
            continue
        return d if d <= today else d.replace(year=d.year - 1)
    return None


def format_date(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def format_posted(text: str) -> str:
    """"Sep 25, 2026" when parseable, the original text otherwise, "" if empty."""
    d = parse_posted(text)
    if d:
        return format_date(d)
    text = (text or "").strip()
    # The email adds its own "Posted" label; don't double it ("Posted Today").
    return text[len("posted "):] if text.lower().startswith("posted ") else text
