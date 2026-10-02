"""P3-15 on the real account: the clock does what the lazy paths of the server do (opt-in, a few cents).

Needs the stacks of the other AWS tests plus ``FairTableWorkers``. The slow test waits for a real ten-minute hold
to run out and for the schedule to notice, so it takes about twelve minutes; the others take a minute or two.
Run with ``AWS_TEST_DINER`` / ``AWS_TEST_WAITER`` set to diners that hold nothing at Luna.
"""

import json
import os
import time
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from botocore.exceptions import ClientError
from test_demo_flow import call, sub_of, web  # noqa: F401
from test_gateway import PREFIX, gateway  # noqa: F401
from test_runtime_smoke import cognito  # noqa: F401
from test_tokens import sign_in  # noqa: F401

from server.domain import fairdrop as fd
from server.store import TxOp, keys

pytestmark = pytest.mark.aws
FUNCTION = "FairTableWorkers"
LUNA = "luna-trattoria"
HOLDER = os.environ.get("AWS_TEST_DINER", "diner-bob")
WAITER = os.environ.get("AWS_TEST_WAITER", "diner-carol")


@pytest.fixture(scope="module")
def lam():
    client = boto3.client("lambda")
    try:
        config = client.get_function_configuration(FunctionName=FUNCTION)
    except ClientError as e:
        pytest.skip(f"{FUNCTION} is not deployed: {e}")
    return {"client": client, "config": config}


def invoke(lam) -> dict:
    out = lam["client"].invoke(FunctionName=FUNCTION, Payload=b"{}")
    body = json.loads(out["Payload"].read())
    assert "FunctionError" not in out, body
    return body


def test_the_function_runs_and_reports_what_it_did(lam):
    assert lam["config"]["Runtime"] == "python3.12" and lam["config"]["Architectures"] == ["arm64"]
    summary = invoke(lam)
    assert set(summary) == {"holds_released", "drops_drawn"} and isinstance(summary["holds_released"], int)


def test_the_schedule_calls_the_function_every_minute():
    logs = boto3.client("logs")
    start = int((time.time() - 600) * 1000)
    ticks = []
    for _ in range(3):  # a fresh deployment needs a minute or two before the first tick
        events = logs.filter_log_events(logGroupName=f"/aws/lambda/{FUNCTION}", startTime=start,
                                        filterPattern='"workers tick"').get("events", [])
        ticks = sorted(e["timestamp"] for e in events)
        if len(ticks) >= 3:
            break
        time.sleep(60)
    assert len(ticks) >= 3, f"only {len(ticks)} ticks in the last ten minutes"
    gaps = [(b - a) / 1000 for a, b in zip(ticks, ticks[1:], strict=False)]
    assert min(gaps) > 20 and max(gaps) < 130, gaps  # about one a minute (the same minute may log a retry twice)


async def hold_and_expire(gateway, cognito, web, who):  # noqa: F811
    token = sign_in(cognito, "alexa-plus-sim", who)
    day = (datetime.now(UTC).date() + timedelta(days=5)).isoformat()
    slots = (await call(gateway, token, "availability_check", restaurant_id=LUNA, date=day,
                        time_window="21:00-21:00", party_size=2)).structuredContent["slots"]
    if not slots:  # 21:00 is not on the menu: the earliest slot of the day
        slots = (await call(gateway, token, "availability_check", restaurant_id=LUNA, date=day,
                            time_window="17:30-20:30", party_size=2)).structuredContent["slots"]
    held = await call(gateway, token, "reservation_hold", offer_id=slots[0]["offer_id"],
                      idempotency_key=f"worker-hold-{datetime.now(UTC).strftime('%H%M%S')}")
    assert not held.isError, held.structuredContent
    return held.structuredContent["hold_id"], day


@pytest.mark.asyncio
async def test_a_hold_nobody_touches_is_released_by_the_clock(gateway, cognito, web, lam):  # noqa: F811
    hold_id, _day = await hold_and_expire(gateway, cognito, web, HOLDER)
    store = web["store"]
    assert store.get_hold(hold_id).status == "held"
    deadline = time.time() + 14 * 60  # the hold lasts ten minutes, the schedule looks every minute
    while time.time() < deadline and store.get_hold(hold_id).status == "held":
        time.sleep(20)
    hold = store.get_hold(hold_id)
    assert hold.status == "expired", f"still {hold.status} after {14} minutes: the workers did not release it"
    # the release came from the clock: the diner made no request in between, and the user counter went down with it
    assert not [h for h in store.holds_of_user(sub_of(cognito, HOLDER)) if h.status == "held" and h.hold_id == hold_id]


def next_friday_drop() -> str:
    day = datetime.now(UTC).date() + timedelta(days=1)
    while day.weekday() != 4:
        day += timedelta(days=1)
    return f"drop-sakura-{day.isoformat()}"


@pytest.mark.asyncio
async def test_a_due_drop_is_drawn_by_the_clock_and_its_audit_is_copied_to_s3(gateway, cognito, web, lam):  # noqa: F811
    store, did = web["store"], next_friday_drop()
    drop = store.get_drop(did)
    assert drop is not None and drop.status == "open", f"{did} is {drop and drop.status}: run `aws_ctl.py seed` first"
    token = sign_in(cognito, "alexa-plus-sim", WAITER)
    entered = await call(gateway, token, "waitlist_watch", drop_id=did, party_size=2,
                         idempotency_key=f"worker-drop-{datetime.now(UTC).strftime('%H%M%S')}")
    assert not entered.isError, entered.structuredContent
    key = keys.drop(did)  # make the draw due now (the seeded one is a day before the seats)
    store.transact([TxOp("Update", key={"PK": key.pk, "SK": key.sk}, update="SET drop_at = :now",
                         values={":now": (datetime.now(UTC) - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")})])
    deadline = time.time() + 5 * 60
    while time.time() < deadline and store.get_drop(did).status != "allocated":
        time.sleep(15)
    drop = store.get_drop(did)
    assert drop.status == "allocated", "the workers did not draw the drop"
    bucket = lam["config"]["Environment"]["Variables"]["AUDIT_BUCKET"]
    body = boto3.client("s3").get_object(Bucket=bucket, Key=f"drops/{did}.json")["Body"].read()
    published = json.loads(body)
    assert published == drop.audit and fd.verify_audit(published) == []  # anyone can recompute the draw from the copy
    inbox = [m["subject"] for m in store.list_inbox(sub_of(cognito, WAITER))]
    assert "You won the draw" in inbox  # one entry, one place: the only entrant wins
