"""P1-15: Fair Drop core (pure): commitment, tickets, verifiable order, audit."""

import copy
import hashlib
import hmac

import pytest

from server.domain import fairdrop as fd

SEED = bytes(range(32))
DROP = fd.Drop("drop-sakura-2026-10-02", "sakura-counter", "2026-10-02", ("2000#T2", "2000#T4"),
               "2026-10-01T12:00:00Z", "2026-10-01T20:00:00Z", fd.commitment(SEED))


def ids(*subs: str) -> list[str]:
    return [fd.entry_id(DROP.drop_id, s) for s in subs]


def entries(*subs: str) -> list[fd.DropEntry]:
    return [
        fd.DropEntry(fd.entry_id(DROP.drop_id, s), DROP.drop_id, s, s, "verified", "sim",
                     frozenset({"fairtable/book"}), 2, f"2026-10-01T12:0{i}:00Z")
        for i, s in enumerate(subs)
    ]


# ---------------------------------------------------------------- commitment and seeds
def test_the_commitment_is_the_sha256_of_the_seed():
    assert fd.commitment(SEED) == hashlib.sha256(SEED).hexdigest() == DROP.commitment
    assert fd.commitment(SEED) != fd.commitment(bytes(32))
    assert len(fd.commitment(SEED)) == 64


def test_local_seeds_are_32_random_bytes():
    provider = fd.LocalSeedProvider()
    first, second = provider.new_seed(), provider.new_seed()
    assert len(first) == fd.SEED_BYTES and first != second


def test_fixed_seed_provider_is_reproducible_and_cycles():
    provider = fd.FixedSeedProvider(b"a" * 32, b"b" * 32)
    assert [provider.new_seed() for _ in range(3)] == [b"a" * 32, b"b" * 32, b"a" * 32]


def test_the_kms_provider_is_a_thin_wrapper_around_generate_random():
    class FakeKms:
        def __init__(self):
            self.calls = []

        def generate_random(self, **kwargs):
            self.calls.append(kwargs)
            return {"Plaintext": b"k" * 32}

    kms = FakeKms()
    assert fd.KmsSeedProvider(kms).new_seed() == b"k" * 32
    assert kms.calls == [{"NumberOfBytes": 32}]


# ---------------------------------------------------------------- tickets
def test_a_ticket_id_is_stable_per_person_and_drop_and_hides_the_person():
    a = fd.entry_id("drop-1", "dev-alice")
    assert a == fd.entry_id("drop-1", "dev-alice")
    assert a != fd.entry_id("drop-1", "dev-bob") != fd.entry_id("drop-2", "dev-bob")
    assert "alice" not in a
    drop_id, digest = fd.split_entry_id(a)
    assert drop_id == "drop-1" and digest == fd.entry_hash("drop-1", "dev-alice")


@pytest.mark.parametrize("bad", ["", "no-separator", "~abc", "drop~short", "drop~" + "z" * 63])
def test_malformed_ticket_ids_do_not_parse(bad):
    assert fd.split_entry_id(bad) is None


def test_drop_ids_may_contain_dashes_but_the_split_uses_the_last_separator():
    assert fd.split_entry_id(fd.entry_id("drop-sakura-2026-10-02", "u"))[0] == "drop-sakura-2026-10-02"


# ---------------------------------------------------------------- the order
def test_order_is_hmac_ascending_and_ignores_arrival_order():
    tickets = ids("a", "b", "c", "d", "e")
    order = fd.order_entries(SEED, tickets)
    keys = [hmac.new(SEED, e.encode(), hashlib.sha256).hexdigest() for e in order]
    assert keys == sorted(keys)
    assert fd.order_entries(SEED, list(reversed(tickets))) == order  # who came first does not matter
    assert sorted(order) == sorted(tickets)


def test_the_seed_decides_the_order():
    tickets = ids("a", "b", "c", "d", "e", "f")
    assert fd.order_entries(SEED, tickets) != fd.order_entries(b"\x01" * 32, tickets)


def test_every_position_is_roughly_equally_likely():
    """A sanity check on fairness: with random seeds each of 4 tickets wins first about 25% of the time."""
    tickets = ids("a", "b", "c", "d")
    firsts = {t: 0 for t in tickets}
    for i in range(400):
        firsts[fd.order_entries(hashlib.sha256(str(i).encode()).digest(), tickets)[0]] += 1
    assert all(60 <= n <= 140 for n in firsts.values()), firsts


# ---------------------------------------------------------------- audit
def good_audit():
    es = entries("a", "b", "c", "d")
    order = fd.order_entries(SEED, [e.entry_id for e in es])
    outcomes = {order[0]: ("won", None), order[1]: ("skipped", "S2_agent_share_of_covers"),
                order[2]: ("won", None), order[3]: ("lost", None)}
    return fd.build_audit(DROP, SEED, es, outcomes, "2026-10-01T20:00:05Z")


def test_a_good_audit_verifies_and_carries_no_personal_data():
    audit = good_audit()
    assert fd.verify_audit(audit) == []
    assert audit["seed"] == SEED.hex() and audit["capacity"] == 2 and len(audit["winners"]) == 2
    text = str(audit)
    assert not any(s in text for s in ("dev-", "alice")) and audit["entries"][0].startswith("drop-sakura")


def test_the_entries_are_listed_in_arrival_order_and_the_order_in_draw_order():
    audit = good_audit()
    assert audit["entries"] == [fd.entry_id(DROP.drop_id, s) for s in "abcd"]
    assert [r["entry_id"] for r in audit["order"]] == fd.order_entries(SEED, audit["entries"])


def tamper(mutate) -> list[str]:
    audit = copy.deepcopy(good_audit())
    mutate(audit)
    return fd.verify_audit(audit)


def test_every_kind_of_tampering_is_detected():
    assert any("commitment" in p for p in tamper(lambda a: a.update(seed=(b"x" * 32).hex())))
    assert any("commitment" in p for p in tamper(lambda a: a.update(commitment="0" * 64)))
    assert any("order" in p for p in tamper(lambda a: a["order"].reverse()))
    assert any("draw key" in p for p in tamper(lambda a: a["order"][0].update(draw_key="0" * 64)))
    assert any("winners" in p for p in tamper(lambda a: a.update(winners=a["winners"][:1])))
    assert any("appears twice" in p for p in tamper(lambda a: a["entries"].append(a["entries"][0])))
    assert any("more winners" in p for p in tamper(lambda a: a.update(capacity=1)))
    assert any("without a reason" in p for p in tamper(lambda a: a["order"][1].pop("reason")))


def test_passing_over_someone_for_a_later_person_is_detected():
    def unfair(a):  # first person 'lost' while places were left
        a["order"][0]["outcome"] = "lost"
        a["winners"] = [r["entry_id"] for r in a["order"] if r["outcome"] == "won"]

    assert any("places were left" in p for p in tamper(unfair))


def test_a_malformed_audit_is_reported_not_crashed():
    assert fd.verify_audit({}) and fd.verify_audit({"seed": "zz"})


def test_the_pending_audit_never_contains_the_seed():
    pending = fd.pending_audit(DROP)
    assert "seed" not in pending and pending["commitment"] == DROP.commitment and pending["status"] == "open"
