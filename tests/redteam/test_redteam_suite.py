"""P1-22: red-team attacks RT1 to RT12 (design section 9.5) against a real server, under A0, A1 and A2.

Every attack is a deterministic scenario in ``eval/redteam.py`` run in its own fresh environment. Under A1
all twelve must be blocked, by the layer the design names. Under A0 and A2 the attacks that depend on the
weakened layer must succeed: if they did not, the comparison would prove nothing.
"""

import pytest

from eval.redteam import ATTACKS, Outcome, main, run_redteam, to_markdown

pytestmark = pytest.mark.ddb

# The attacks only the policy layer stops: an open store lets them through (D-027). The others are held by
# token verification, the rate limiter or the database's own conditions, in every configuration.
POLICY_ONLY_A0 = {"RT1", "RT3", "RT5", "RT8"}
POLICY_ONLY_A2 = {"RT5"}  # without the voice guards only the confirm-without-a-read-back attack gets through


@pytest.fixture(scope="module")
def results(ddb_client) -> dict[str, list[Outcome]]:
    import asyncio

    return {c: asyncio.run(run_redteam(c)) for c in ("A0", "A1", "A2")}


def by_id(outcomes: list[Outcome]) -> dict[str, Outcome]:
    return {o.id: o for o in outcomes}


def test_the_catalogue_has_the_twelve_attacks():
    assert list(ATTACKS) == [f"RT{i}" for i in range(1, 13)]


@pytest.mark.parametrize("attack", list(ATTACKS))
def test_a1_blocks_every_attack_at_the_expected_layer(results, attack):
    o = by_id(results["A1"])[attack]
    assert o.blocked, f"{o.id} {o.title}: not blocked ({o.observed}; {o.detail})"
    assert o.as_expected, f"{o.id}: stopped by {o.observed}, expected {o.expected} (or {o.accept})"


def test_a0_lets_exactly_the_policy_attacks_through(results):
    succeeded = {o.id for o in results["A0"] if not o.blocked}
    assert succeeded == POLICY_ONLY_A0


def test_a2_lets_only_the_silent_confirm_through(results):
    succeeded = {o.id for o in results["A2"] if not o.blocked}
    assert succeeded == POLICY_ONLY_A2


def test_the_attacks_that_do_not_need_the_policy_layer_are_blocked_everywhere(results):
    """RT2, RT4, RT6, RT7, RT9 to RT12: verification, rate limit and database conditions hold under A0 too."""
    for config in ("A0", "A1", "A2"):
        held = by_id(results[config])
        for attack in ("RT2", "RT4", "RT6", "RT7", "RT9", "RT10", "RT11", "RT12"):
            assert held[attack].blocked, f"{attack} under {config}: {held[attack]}"


def test_the_summary_table_shows_x_of_12_per_configuration(results):
    table = to_markdown(results)
    assert "| | **Blocked** | | 8/12 | 12/12 | 11/12 |" in table
    assert table.count("**SUCCEEDED**") == 5
    assert "| RT9 | Twenty simultaneous holds on one table | SLOT_TAKEN |" in table


def test_the_command_line_runs_and_signals_success_by_exit_code(capsys, ddb_client):
    assert main(["--config", "A1"]) == 0
    assert "12/12" in capsys.readouterr().out
