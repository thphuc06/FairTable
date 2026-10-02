"""The simulated diner: the one who answers the read-back aloud (docs/DECISIONS.md D-051).

There is nothing to click any more: a booking is confirmed by a spoken yes, which the assistant relays. The
simulated diner only decides what to say. The evaluation harness knows what was said, so it can tell a booking
the diner agreed to from one the assistant made up.
"""

YES = "Yes, please."
NO = "No, thanks."


class SimulatedUser:
    def __init__(self, answer: str = "approve") -> None:
        if answer not in ("approve", "decline", "ignore"):
            raise ValueError("answer must be approve, decline or ignore")
        self.answer = answer

    @property
    def speaks(self) -> bool:
        """False for a diner who never answers."""
        return self.answer != "ignore"

    @property
    def says_yes(self) -> bool:
        return self.answer == "approve"

    def reply(self) -> str:
        return YES if self.says_yes else NO
