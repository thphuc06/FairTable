"""The simulated diner: the one who signs in and answers the consent page, outside the conversation.

The assistant never gets these abilities (that is the point of step-up): approving needs a sign-in as
the diner. ``browser`` is any client with ``get`` and ``post`` that keeps cookies and returns relative
redirects untouched (an ``httpx.Client(base_url=...)`` in the Docker profile, a Starlette test client
in tests).
"""

import re
from typing import Any
from urllib.parse import urlparse

CSRF = re.compile(r"name='csrf' value='([^']+)'")


class ConsentError(Exception):
    """The consent page did not behave as a diner expects (not signed in, expired, not theirs...)."""


class SimulatedUser:
    def __init__(self, browser: Any, username: str, password: str) -> None:
        self._browser = browser
        self._username = username
        self._password = password
        self._signed_in = False

    def sign_in(self) -> None:
        r = self._browser.post("/login", data={"username": self._username, "password": self._password, "next": "/"})
        if r.status_code not in (200, 303):
            raise ConsentError(f"sign-in was refused ({r.status_code})")
        self._signed_in = True

    def _decide(self, consent_url: str, decision: str) -> str:
        """Open the consent link, choose, and return the page the diner ends on (text)."""
        if not self._signed_in:
            self.sign_in()
        path = urlparse(consent_url).path
        page = self._browser.get(path)
        if page.status_code != 200:
            raise ConsentError(f"the consent page answered {page.status_code}")
        match = CSRF.search(page.text)
        if match is None:
            return page.text  # already answered
        r = self._browser.post(f"{path}/decision", data={"decision": decision, "csrf": match.group(1)})
        if r.status_code != 303:
            raise ConsentError(f"the decision was refused ({r.status_code})")
        return self._browser.get(path).text

    def approve_consent(self, consent_url: str) -> str:
        return self._decide(consent_url, "approve")

    def decline(self, consent_url: str) -> str:
        return self._decide(consent_url, "decline")
