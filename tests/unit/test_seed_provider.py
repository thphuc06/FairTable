"""P3-15: where the Fair Drop seed comes from (scripts/seed.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from seed import seed_provider  # noqa: E402

from server.domain.fairdrop import KmsSeedProvider, LocalSeedProvider  # noqa: E402


def test_the_seed_comes_from_this_machine_unless_kms_is_asked_for():
    assert isinstance(seed_provider({}), LocalSeedProvider)
    assert isinstance(seed_provider({"SEED_PROVIDER": "local"}), LocalSeedProvider)
    assert len(LocalSeedProvider().new_seed()) == 32


def test_kms_is_chosen_by_name_and_builds_its_own_client(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")  # a client needs a region; no call is made here
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    assert isinstance(seed_provider({"SEED_PROVIDER": "KMS"}), KmsSeedProvider)
