"""Behavioural scenarios for G1-G4, shared by the local Cedar tests and (later) the AgentCore
Gateway tests (plan decision D5: two policy sets, one behavioural suite).

Each scenario says who calls which tool with what party size, and the expected outcome. A runner
turns it into a real call; only the runner differs between the local and the Gateway suites.
"""

from dataclasses import dataclass, field

from server.domain.tool_names import ToolName

BOOK = "fairtable/book"


@dataclass(frozen=True)
class Caller:
    sub: str = "u1"
    username: str | None = "alice"
    agent_tier: str | None = "verified"
    agent_id: str | None = "alexa-plus-sim"
    scopes: tuple[str, ...] = (BOOK,)


@dataclass(frozen=True)
class Scenario:
    id: str
    caller: Caller
    action: ToolName
    party_size: int
    expected: str  # "allow" | "deny"
    expected_rules: tuple[str, ...]
    note: str = field(default="", compare=False)


VERIFIED_USER = Caller()
BOT_NO_CLAIMS = Caller(sub="bot", username=None, agent_tier=None, agent_id=None)
BOT_WITH_TIER_NO_USER = Caller(sub="bot", username=None)  # scope + tier, but no human behind it

SCENARIOS: tuple[Scenario, ...] = (
    Scenario("read-verified-user", VERIFIED_USER, ToolName.AVAILABILITY_CHECK, 2,
             "allow", ("G1_reads_any_valid_jwt",)),
    Scenario("read-bot-without-claims", BOT_NO_CLAIMS, ToolName.RESTAURANT_SEARCH, 0,
             "allow", ("G1_reads_any_valid_jwt",), "M2M bots may read"),
    Scenario("read-without-scope", Caller(scopes=()), ToolName.WAITLIST_STATUS, 0,
             "allow", ("G1_reads_any_valid_jwt",), "reads need only a valid token"),
    Scenario("read-unverified-agent", Caller(agent_tier="unverified"), ToolName.WAITLIST_STATUS, 0,
             "allow", ("G1_reads_any_valid_jwt",)),
    Scenario("write-verified-user", VERIFIED_USER, ToolName.RESERVATION_HOLD, 4,
             "allow", ("G2_writes_need_user_and_scope",)),
    Scenario("write-waitlist-watch", VERIFIED_USER, ToolName.WAITLIST_WATCH, 2,
             "allow", ("G2_writes_need_user_and_scope",)),
    Scenario("write-party-of-10-is-fine", VERIFIED_USER, ToolName.RESERVATION_HOLD, 10,
             "allow", ("G2_writes_need_user_and_scope",)),
    Scenario("write-without-book-scope", Caller(scopes=()), ToolName.RESERVATION_HOLD, 2,
             "deny", ("no_permit",), "G2 permit does not match"),
    Scenario("write-by-bot-with-tier-but-no-user", BOT_WITH_TIER_NO_USER,
             ToolName.RESERVATION_CONFIRM, 2, "deny", ("no_permit",), "RT3: bot has no username"),
    Scenario("write-token-without-agent_tier-claim", Caller(agent_tier=None),
             ToolName.RESERVATION_HOLD, 2, "deny", ("G4_verified_agent_only",),
             "RT1: the has-guard makes a missing claim a deny"),
    Scenario("write-unverified-agent", Caller(agent_tier="unverified"),
             ToolName.RESERVATION_MANAGE, 2, "deny", ("G4_verified_agent_only",)),
    Scenario("write-bot-without-claims", BOT_NO_CLAIMS, ToolName.RESERVATION_HOLD, 2,
             "deny", ("G4_verified_agent_only",), "M2M token: no username, no tier"),
    Scenario("write-party-of-11", VERIFIED_USER, ToolName.RESERVATION_HOLD, 11,
             "deny", ("G3_party_size_max_10",)),
    Scenario("read-party-of-11", VERIFIED_USER, ToolName.AVAILABILITY_CHECK, 11,
             "deny", ("G3_party_size_max_10",), "big groups are refused at search time too"),
    Scenario("write-unverified-and-party-of-12", Caller(agent_tier="unverified"),
             ToolName.RESERVATION_HOLD, 12, "deny",
             ("G3_party_size_max_10", "G4_verified_agent_only"), "both forbids are reported"),
)
