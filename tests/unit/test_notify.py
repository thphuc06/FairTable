"""P3-12: the SNS notifier, with a fake client (no AWS call; the real test is opt-in under tests/aws)."""

import pytest
from joserfc.jwk import KeySet, RSAKey

from server import app as app_module
from server.app import build_deps
from server.config import Settings
from server.identity import StaticJwks
from server.notify import DevInboxNotifier, FanoutNotifier, SnsNotifier

ARN = "arn:aws:sns:us-east-1:111122223333:fairtable-notices"  # a made-up value, not an account of ours


class FakeSns:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def publish(self, **kwargs):
        if self.fail:
            raise RuntimeError("AuthorizationError: not allowed")
        self.calls.append(kwargs)
        return {"MessageId": "m-1"}


def test_a_notice_is_one_publish_to_the_topic_with_no_link_or_id():
    sns = FakeSns()
    SnsNotifier(sns, ARN).notify(
        "dev-alice", subject="A table opened up", body="Luna has a table on Saturday at 7:00 PM.",
        url="http://localhost:8080/secret-link",
    )
    assert sns.calls == [{"TopicArn": ARN, "Subject": "FairTable: A table opened up",
                          "Message": "Luna has a table on Saturday at 7:00 PM."}]
    sent = str(sns.calls)
    assert "dev-alice" not in sent and "secret-link" not in sent  # neither the user id nor the link leaves the server


def test_the_subject_is_one_line_and_shorter_than_100_characters():
    sns = FakeSns()
    SnsNotifier(sns, ARN).notify("u", subject="line one\nline two\t" + "x" * 300, body="b")
    subject = sns.calls[0]["Subject"]
    assert len(subject) <= 99 and "\n" not in subject and "\t" not in subject


def test_a_failing_publish_never_breaks_the_request(caplog):
    SnsNotifier(FakeSns(fail=True), ARN).notify("u", subject="s", body="b")  # no exception
    assert "could not publish" in caplog.text


def test_the_notifier_needs_a_topic():
    with pytest.raises(ValueError):
        SnsNotifier(FakeSns(), "")


def test_fanout_tells_every_notifier_even_when_one_fails():
    told = []

    class Broken:
        def notify(self, *a, **k):
            raise RuntimeError("down")

    class Recorder:
        def notify(self, sub, *, subject, body, url=""):
            told.append((sub, subject))

    FanoutNotifier(Broken(), Recorder()).notify("u", subject="s", body="b")
    assert told == [("u", "s")]


def test_the_topic_comes_from_the_environment_and_is_empty_by_default():
    assert Settings.from_env({}).notify_topic_arn == ""
    assert Settings.from_env({"NOTIFY_TOPIC_ARN": f" {ARN} "}).notify_topic_arn == ARN


def deps_for(**env):
    settings = Settings.from_env({"TABLE_NAME": "unused", "DDB_ENDPOINT_URL": "http://127.0.0.1:1", **env})
    return build_deps(settings, jwks=StaticJwks(KeySet([RSAKey.generate_key(2048, auto_kid=True)]).as_dict(private=False)))


def test_without_a_topic_only_the_dev_inbox_is_used():
    assert isinstance(deps_for().notifier, DevInboxNotifier)


def test_with_a_topic_the_dev_inbox_stays_and_sns_is_added(monkeypatch):
    fake = FakeSns()
    monkeypatch.setattr(app_module, "sns_client", lambda settings: fake)
    deps = deps_for(NOTIFY_TOPIC_ARN=ARN)
    assert isinstance(deps.notifier, FanoutNotifier)
    kinds = [type(n).__name__ for n in deps.notifier._notifiers]
    assert kinds == ["DevInboxNotifier", "SnsNotifier"]
