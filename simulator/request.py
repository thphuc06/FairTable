"""Read a diner's sentence into a ``Goal`` (used by the mock model on the chat page).

Deliberately small: a party size, a time, a date word and a few key words. Anything it cannot read
is left empty and the persona asks or says what it can do. A real model does this itself.
"""

import re
from datetime import date, timedelta

from simulator.personas import Goal

TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\b([01]?\d|2[0-3]):([0-5]\d)\b", re.IGNORECASE)
PARTY = re.compile(r"\b(?:for|party of|table of)\s+(\d{1,2})\b|\b(\d{1,2})\s+(?:people|persons|guests|of us)\b", re.IGNORECASE)
ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
IN_DAYS = re.compile(r"\bin\s+(\d{1,2})\s+days?\b", re.IGNORECASE)
STOP = {"a", "the", "at", "for", "table", "book", "me", "please", "tonight", "tomorrow", "today", "in", "on",
        "of", "and", "to", "my", "us", "people", "reserve", "reservation", "i", "want", "would", "like",
        "can", "you", "get", "find", "pm", "am", "days", "day", "party", "watch", "wait", "waitlist",
        "notify", "when", "opens", "one", "opening", "guests", "persons", "with", "need"}
WATCH_WORDS = ("waitlist", "wait list", "notify me", "let me know", "when a table opens", "watch")


def parse_time(text: str) -> str | None:
    m = TIME.search(text)
    if not m:
        return None
    if m.group(3):
        hour, minute, meridian = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridian == "pm" else 0)
    else:
        hour, minute = int(m.group(4)), int(m.group(5))
    return f"{hour:02d}:{minute:02d}"


def parse_date(text: str, today: date) -> str | None:
    if m := ISO_DATE.search(text):
        return m.group(1)
    lowered = text.lower()
    if "tomorrow" in lowered:
        return (today + timedelta(days=1)).isoformat()
    if "today" in lowered or "tonight" in lowered:
        return today.isoformat()
    if m := IN_DAYS.search(text):
        return (today + timedelta(days=int(m.group(1)))).isoformat()
    return None


def parse_request(text: str, today: date) -> Goal | None:
    """A booking or waitlist goal, or None when the sentence has no date (nothing to act on yet)."""
    day = parse_date(text, today)
    if day is None:
        return None
    party = PARTY.search(text)
    words = [w for w in re.findall(r"[a-zA-Z]+", TIME.sub(" ", ISO_DATE.sub(" ", text))) if w.lower() not in STOP]
    kind = "watch" if any(w in text.lower() for w in WATCH_WORDS) else "book"
    return Goal(
        kind=kind, date=day, time=parse_time(text) or "19:00",
        party_size=int(party.group(1) or party.group(2)) if party else 2,
        restaurant=" ".join(w.lower() for w in words[:3]),
    )
