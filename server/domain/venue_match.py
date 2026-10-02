"""Find restaurants by a name that a speech recogniser may have got a little wrong (pure functions, no I/O).

A diner says a name, the assistant's speech-to-text writes it down, and the tool gets a string like "Luna Tratoria"
or "Embers Grill". The match must be forgiving, and it must say how sure it is, so that the assistant can read the
name back to the diner when it is not sure. Everything here is deterministic (standard library only); no model.

* ``exact``  every word of the query is a word of the restaurant's name ("Luna", "luna trattoria", "GRILL").
* ``topic``  every word of the query is a word of the name, cuisine, city or description ("italian", "riverside").
* ``close``  the query sounds or spells like the name but is not it ("Luna Tratoria", "Embers Grill"); the score
  tells how close (0..1). A close match must be confirmed with the diner before it is used.
"""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from server.domain.models import Venue

EXACT, TOPIC, CLOSE = "exact", "topic", "close"
MIN_CLOSE = 0.72  # below this a name is not offered at all
TOKEN_FLOOR = 0.55  # a word of the query that matches no word of the name this well counts as unmatched
TIE = 0.08  # two close matches this near each other are put to the diner as a choice
FILLER = frozenset({"the", "a", "an", "at", "please", "restaurant", "table"})  # words a diner adds around a name

_SOUND = (("ph", "f"), ("ck", "k"), ("kh", "k"), ("q", "k"), ("c", "k"), ("z", "s"), ("y", "i"), ("h", ""))


def normal(text: str) -> str:
    """Lower case, without accents or punctuation, single spaces."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", plain.lower()).strip()


def sound(text: str) -> str:
    """A rough spelling by sound: "Kafe" and "Cafe", "Sakura" and "Sacura", "Tratoria" and "Trattoria" agree."""
    out = normal(text)
    for old, new in _SOUND:
        out = out.replace(old, new)
    return re.sub(r"(.)\1+", r"\1", out)


def _tokens_score(query: str, name: str) -> float:
    """Average, over the words of the query, of the best match with a word of the name."""
    q, n = query.split(), name.split()
    if not q or not n:
        return 0.0
    total = 0.0
    for word in q:
        best = max(SequenceMatcher(None, word, other).ratio() for other in n)
        total += best if best >= TOKEN_FLOOR else 0.0
    return total / len(q)


def closeness(query: str, name: str) -> float:
    """0..1: how much the query looks or sounds like the name (1.0 only for the same words)."""
    best = 0.0
    for form in (normal, sound):
        q, n = form(query), form(name)
        if not q or not n:
            continue
        best = max(best, SequenceMatcher(None, q, n).ratio(), _tokens_score(q, n))
    return round(min(best, 0.99), 2)  # 1.0 is kept for an exact match


@dataclass(frozen=True)
class Match:
    venue: Venue
    kind: str  # EXACT, TOPIC or CLOSE
    score: float  # 1.0 for EXACT and TOPIC


def classify(query: str, venue: Venue) -> Match | None:
    words = [w for w in normal(query).split() if w not in FILLER]
    if not words:
        return Match(venue, EXACT, 1.0)  # no query: everything is listed
    if all(w in set(normal(venue.name).split()) for w in words):
        return Match(venue, EXACT, 1.0)
    text_words = set(normal(f"{venue.name} {venue.cuisine} {venue.city} {venue.description}").split())
    if all(w in text_words for w in words):
        return Match(venue, TOPIC, 1.0)
    score = closeness(" ".join(words), venue.name)
    return Match(venue, CLOSE, score) if score >= MIN_CLOSE else None


def rank(query: str, venues: list[Venue]) -> list[Match]:
    """All usable matches, best first: exact names, then topics, then close names by score (ties by name)."""
    order = {EXACT: 0, TOPIC: 1, CLOSE: 2}
    found = [m for v in venues if (m := classify(query, v)) is not None]
    if any(m.kind != CLOSE for m in found):
        found = [m for m in found if m.kind != CLOSE]  # a name that is found is not mixed with look-alikes
    return sorted(found, key=lambda m: (order[m.kind], -m.score, m.venue.name))


def needs_confirmation(matches: list[Match]) -> bool:
    """True when the best result is only a close match of a name: the assistant must read it back first."""
    return bool(matches) and matches[0].kind == CLOSE


def is_choice(matches: list[Match]) -> bool:
    """True when the two best close matches are so near each other that the diner should pick one."""
    close = [m for m in matches if m.kind == CLOSE]
    return len(close) > 1 and close[0].score - close[1].score < TIE
