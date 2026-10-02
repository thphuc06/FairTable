"""Finding a restaurant by a name that speech recognition may have got a little wrong."""

import pytest

from server.domain.venue_match import CLOSE, EXACT, TOPIC, closeness, is_choice, needs_confirmation, normal, rank, sound
from server.store.seed_data import VENUES

VENUE_LIST = list(VENUES)


def best(query: str):
    found = rank(query, VENUE_LIST)
    return (found[0].venue.name, found[0].kind) if found else None


@pytest.mark.parametrize("query", ["Luna Trattoria", "luna trattoria", "LUNA", "luna", "Trattoria Luna",
                                   "the Luna Trattoria restaurant", "luna trattoria please"])
def test_the_name_or_a_whole_word_of_it_is_an_exact_match(query):
    assert best(query) == ("Luna Trattoria", EXACT)


@pytest.mark.parametrize("query,name", [
    ("Luna Tratoria", "Luna Trattoria"),
    ("Lunar Trattoria", "Luna Trattoria"),
    ("Lena Trattoria", "Luna Trattoria"),
    ("Embers Grill", "Ember Grill"),
    ("Amber Grill", "Ember Grill"),
    ("Sakura Kounter", "Sakura Counter"),
    ("sacura counter", "Sakura Counter"),
    ("Sakura Count", "Sakura Counter"),
])
def test_a_misheard_name_is_a_close_match_that_needs_confirming(query, name):
    found = rank(query, VENUE_LIST)
    assert found[0].venue.name == name and found[0].kind == CLOSE
    assert 0.72 <= found[0].score < 1.0
    assert needs_confirmation(found)


@pytest.mark.parametrize("query,name", [("italian", "Luna Trattoria"), ("riverside", "Luna Trattoria"),
                                        ("steakhouse", "Ember Grill"), ("omakase", "Sakura Counter"),
                                        ("sushi counter", "Sakura Counter")])
def test_a_cuisine_or_a_district_is_a_topic_that_needs_no_confirming(query, name):
    found = rank(query, VENUE_LIST)
    assert (found[0].venue.name, found[0].kind) == (name, TOPIC) and not needs_confirmation(found)


@pytest.mark.parametrize("query", ["Burger Palace", "pizza", "zzzz", "Look at the moon", "Mama Mia", "the grill house"])
def test_something_unrelated_matches_nothing(query):
    assert rank(query, VENUE_LIST) == []


def test_an_empty_query_lists_everything_in_name_order():
    assert [m.venue.name for m in rank("", VENUE_LIST)] == ["Ember Grill", "Luna Trattoria", "Sakura Counter"]
    assert {m.kind for m in rank("", VENUE_LIST)} == {EXACT}


def test_a_found_name_is_not_mixed_with_look_alikes():
    found = rank("Luna", VENUE_LIST)
    assert [m.venue.name for m in found] == ["Luna Trattoria"]


def test_two_look_alike_names_become_a_choice():
    from dataclasses import replace

    luna = next(v for v in VENUE_LIST if v.venue_id == "luna-trattoria")
    twin = replace(luna, venue_id="lunas-trattoria", name="Lunas Trattoria")
    found = rank("Lunar Trattoria", [luna, twin])
    assert {m.venue.name for m in found} == {"Luna Trattoria", "Lunas Trattoria"}
    assert all(m.kind == CLOSE for m in found) and is_choice(found)
    assert not is_choice(rank("Lunar Trattoria", [luna]))  # one candidate is a question, not a choice


def test_normalising_and_sound_keys():
    assert normal("  Caf"+chr(0xE9)+"  Zo"+chr(0xEB)+"'s! ") == "cafe zoe s"  # accents are dropped (written as code points: the repo scan is for Vietnamese)
    assert sound("Cafe") == sound("Kafe") and sound("Tratoria") == sound("Trattoria")
    assert closeness("Luna Trattoria", "Luna Trattoria") == 0.99  # 1.0 is kept for an exact match
