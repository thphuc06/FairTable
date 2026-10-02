# Plan P3-10: voice confirmation, no mandate, seven tools

Status: **built locally on 2026-10-02 (D-055 lists where it differs from this plan: signed token instead of a bare hash, no new storage); the AWS step is not done.** Decisions behind it: D-051 (confirmation by voice), D-053 (no mandate, seven tools). Written 2026-10-02 from a read of the current code (`server/ops/confirm.py`, `server/tools/stepup.py`, `server/consent.py`, `policies/*.cedar`, `server/kernel/pep2.py`); nothing was run for this plan. Sizes below are counts of files that mention the old design, not estimates of effort.

## 1. What the user experiences (and what Alexa's model must do)

```
diner : "Book Luna for two tonight at seven."
model : restaurant_search, availability_check
model : reservation_hold(slot_token, idempotency_key)
server: held for 10 min. Returns terms, read_back text, terms_hash.
model : (says) "Luna Trattoria, tonight at 7, table for two. Free cancellation. Shall I book it?"
diner : "Yes."
model : reservation_confirm(hold_id, terms_hash, user_confirmed=true, idempotency_key)
server: checks the hash, the pause, the hold; books; returns "Booked. Your code is ..."
```

The pause rule, with an example. The server remembers when it handed over the read-back (the hold's creation time). A confirm that arrives less than `MIN_PAUSE` after it is refused: a model that calls hold and confirm in the same breath, without letting the diner answer, cannot get through. A diner needs a few seconds to hear the sentence and say "yes". Values to start with: **3 s**, and **6 s when the booking has a fee**; configurable, to be measured with a real model and a real voice in P3-11 (not measured today).

Refusals are spoken, never technical: "I have not heard the diner's yes yet. Read the details back and ask." No codes, ids or tool names in the text the model reads out (Alexa requirement 2).

## 2. Design

**Tools: seven** (`mandate_status` removed): `restaurant_search`, `availability_check`, `reservation_hold`, `reservation_confirm`, `reservation_manage`, `waitlist_watch`, `waitlist_status`.

**Read-back record.** Reuse the approval storage as a `Readback` record: subject (hold id, or reservation id for a cancel with a fee), kind (`confirm` | `cancel_fee`), `sub`, `terms_hash` (the existing `terms_hash`, fee included), `created_at`, `expires_at`, status `open` -> `used`. It is created in the hold's own transaction (confirm) or on the first cancel call that meets a fee (cancel). It is consumed in the confirm/cancel transaction, so a read-back works once.

**`reservation_hold`** result gains `read_back` (the sentence), `terms_hash`, `min_pause_s`, and a `next_step` that says: read this back, wait for the diner's answer, then confirm with this hash.

**`reservation_confirm(hold_id, terms_hash, user_confirmed, idempotency_key)`**. Facts for PEP-2: `terms_hash_matches`, `pause_elapsed`, `user_confirmed`. New rules (all `@on_deny("deny")`, each with its own `@id` so the refusal knows why): `S5a_confirm_needs_the_terms_read_back` (hash missing or different), `S5b_confirm_needs_the_diners_answer` (too soon), `S5c_confirm_needs_an_explicit_yes` (`user_confirmed` false). `S3_confirm_needs_mandate` and `P0`'s mandate fact go away; `P0_base` (verified agent) stays.

**`reservation_manage` cancel with a fee.** First call (no hash): refused with `FEE_APPLIES`, a spoken sentence stating the fee, and a hash; the read-back record is created. Second call with the hash, `user_confirmed=true`, after the pause: cancels. `S3b` changes from `step_up` to the same three-rule shape. Fee-free cancel and view/modify are unchanged.

**Stored with every booking:** `confirmation = spoken` (hash, time of read-back, time of confirm) in the same `TransactWriteItems`.

**Stateless everywhere (found by the Alexa+ probe, `docs/alexa-plus-addon-notes.md` section 7):** `MCP_STATELESS` defaults to true in every profile (the stateful mode answers calls without a session id with 400, and Alexa+ sends none that we know of). The simulator's client and the tests must keep working; nothing in the new design needs a session.

**What stays:** S1, S2, S4, G1-G4, P0, idempotency, the lazy hold expiry, the owner's agent-share cap, the lock on drop slots. Fair Drop winners and waitlist matches still end in a hold that is confirmed this way.

**Removed:** mandate (store records, `domain/mandate.py`, `domain/grant.py`, seed mandates, `mandate_status` tool, the Gateway read policy entry for it), approvals-as-consent (`server/consent.py`, `server/tools/stepup.py`, the `-32042` middleware path, `extend_hold`), the consent and permissions pages in `web/`, `CONSENT_REQUIRED` as a link, `CONSENT_DECLINED`. The dev inbox stays for waitlist matches.

**What the guards do not do** (to be written next to every claim of safety): the server cannot hear the diner. A model that learns the hash, waits and calls confirm with `user_confirmed=true` looks the same as a diner who said yes. The guards stop mistakes (not asking, asking too fast, confirming other terms than the ones read) and the caps bound the damage.

## 3. Order of work, each step ends green (tests first, then code)

| Step | Work | Gate |
|---|---|---|
| 0 | Developer reviews this plan; open details settled (section 6) | agreement |
| 1 | **Characterise**: list the tests that describe behaviour to keep, to rewrite and to delete (section 4); tag them in a scratch note, no code change | list reviewed |
| 2 | **Domain and kernel**: `Readback` model, pause and hash checks as pure functions (injected clock), `PolicyContext` fields, S5a/b/c and the changed S3b, schema, shared scenario table | unit tests green, `cedarpy` validates the bundle |
| 3 | **Hold and confirm**: hold creates the read-back, confirm checks and consumes it, `confirmation` stored; idempotent replay, expiry, concurrency (20 confirms, one booking) | integration tests green on DynamoDB Local |
| 4 | **Cancel with a fee**: the two-call flow | integration tests green |
| 5 | **Remove the old design**: mandate, approvals, consent page, step-up, `mandate_status`, seed, owner console untouched; Gateway read policy and target list updated | whole suite green, `ruff` clean, `git grep` finds no live reference |
| 6 | **Simulator and eval**: personas speak the read-back and wait for the diner's turn; the simulated diner answers yes / no / nothing and the clock advances; persona behaviours `eager` (confirms at once), `wrong_hash`, `no_yes`; the safety grader compares bookings with what the diner actually said (I1 restated); A2 = the S5 rules switched off; regenerate the 40 tasks; red team RT5 rewritten, one new attack | A1 passes every task; A0 and A2 show the expected violations |
| 7 | **Docs**: `ARCHITECTURE` inputs, `README` of server/web/eval, devlog, DECISIONS, PLAN 3a; the Alexa+ comparison table updated | review |
| 8 | **AWS** (after the developer's go, account 1905 is up): rebuild the zip, redeploy Runtime, resync the Gateway target (seven tools), update the Gateway read policy, reseed, update and run `tests/aws` | real-AWS tests green; trace of one booking recaptured |
| 9 | **Full gate**: whole local suite in the background, `ruff`, `-m docker` smoke (says first: it stops the developer's compose stack), eval A0/A1/A2 | all green; numbers recorded |

Do the work on a git branch (the developer runs `git`); the old design stays in history, so nothing is lost by deleting it in step 5.

## 4. What the existing tests become (counted from the repo, 48 test files mention the old design)

| Area | Files (approx.) | Fate |
|---|---|---|
| mandate: domain, store, tool `mandate_status`, seed | tests/unit (10), tests/integration (about 8), tests/aws (3), redteam (1) | delete with the code, except cases about venue/slot data |
| approval, consent page, step-up transport, `-32042`, notifier-for-consent | tests/integration (about 14), tests/unit (about 8) | delete; re-express each *behaviour* as a voice-confirmation test (a confirm that does not go through is refused; a refusal books nothing; replay is idempotent; wrong user is refused) |
| shared PEP-2 scenario table | tests/unit/kernel | rewrite for S5a/b/c, S3b |
| `tests/fixtures/eval_starter` and the tests that pin its numbers | tests/integration (ablation, eval run), tests/unit/eval | rewrite the pinned numbers after step 6 |
| Docker smoke, AWS tests (demo flow, gateway, policy) | tests/integration, tests/aws | update flows from "approve on the page" to "say yes" |

## 5. Risks and how they are handled

- **Large change late in the schedule.** Mitigation: the order above keeps the suite green at every step; step 8 (AWS) is separate; the voice demo (P3-11) does not depend on it.
- **Weaker evidence than before** (a scripted persona cannot lie). Mitigation: the evaluation measures mistakes the guards can catch (eager, wrong hash, no yes), is labelled as such, and the documents state what is not proven.
- **A real model may not pass the hash or may wait too long.** The tool descriptions and `next_step` carry the instruction; a failure refuses and tells the model what to do; the hold lasts 10 minutes. Measured with the DeepSeek runs of `tests/aws/test_real_model.py` (rewritten) before any claim.
- **Gateway tool list changes** (seven tools): the interceptor and the allow-list do not name tools; the Gateway read policy does and must be updated; `aws_ctl.py up` handles the two-stage policy deploy.
- **Alexa's client declares no elicitation**, so nothing in this design depends on it.

## 6. Details settled with the developer (D-054, 2026-10-02)
All five proposals accepted, with these changes: the hold of a waitlist match lasts 30 minutes and that of a Fair Drop winner 2 hours (normal holds stay at 10); notifications go through the dev inbox locally and an SNS topic with one subscribed address on AWS (task P3-12, after P3-10); `MCP_STATELESS` becomes true by default.

The original list, for the record:
1. Minimum pause: 3 s, and 6 s with a fee (proposal).
2. `user_confirmed` as an explicit argument (proposal: yes, because it makes the model state the claim and leaves an audit trail).
3. Hold length stays 10 minutes (proposal).
4. Dev inbox kept for waitlist matches (proposal).
5. Fair Drop winners: the hold is made for them as today and confirmed by voice in their next conversation.
