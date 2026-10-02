# P3-10 step 1: what happens to the existing tests

Read from the test names and the code on 2026-10-02 (no test was changed or run for this list). Counts come from the repository: 48 test files mention the old design (mandate, approval, consent, step-up, inbox), 587 tests in them, 88 with one of those words in the name; most of the 587 only use the old design as set-up. "Keep" means the behaviour stays and the test is adapted only where a call changes (a `terms_hash` argument, no mandate in the fixture).

## Core files

| File (tests) | Keep | Rewrite as voice-confirmation behaviour | Delete |
|---|---|---|---|
| `integration/test_reservation_confirm.py` (20) | repeat returns the same booking; already-confirmed hold with a new key points to the booking; nobody confirms another user's or a made-up hold; an expired hold cannot be confirmed and is released (4) | a confirm inside the old mandate becomes "right hash, after the pause, `user_confirmed`: books at once and stores `spoken`"; "outside the mandate gets a consent url" becomes three refusals (no hash, too soon, no explicit yes) that book nothing; "approval for another user or other terms or past its time is worthless" becomes "a hash for other terms, another user's read-back or an expired one is refused"; "an expired approval asks again" becomes "an expired read-back is refused and the hold must be redone"; fee booking needs the longer pause | the dev-inbox-once test, `-32042` (2), "only the URL capability counts", the five hold-lengthening tests, "other ways of leaving the mandate" |
| `integration/test_standing_permission.py` (21) | | | all (D-033, D-053) |
| `integration/test_consent_web.py` (20) | tests of sign-in, session and CSRF that the chat page and owner console still use (to be checked: move them to a file about `web` sessions) | | the consent and permissions pages |
| `unit/domain/test_grant.py` (11) | | | all |
| `integration/test_reservation_manage.py` (16) | view (2), free cancel (4), nobody else's booking, modify (2), inputs, no token (11) | the four "cancel with a fee waits for the user / approve / decline / other fee" become the two-call flow of the plan: first call refused with the fee and a hash, second call after the pause cancels; a wrong or early second call changes nothing | the `-32042` fee test |
| `integration/test_reservation_hold.py` (19) | all, extended: the hold returns terms, read-back sentence, hash and pause | | tests that assert the old result shape if any |
| `integration/test_read_tools.py` (22) | all except the `mandate_status` group | | about 6 `mandate_status` tests |
| `unit/domain/test_read_logic.py` (17) | the rest | | the mandate summary logic (about 3) |
| `unit/kernel/test_pep2.py` (9) | context validation, deny priority, no permit, error fails closed | `test_pep2_cases` table (new facts and rules S5a/b/c, S3b); "all six rules are loaded" changes the count | |
| `unit/kernel/test_variants.py` (6) | A0 tests, "every denial still holds", "PEP-1 is the real one" | A2 tests: "without step-up" becomes "without the voice guards a confirm with no hash, too early or without a yes is simply allowed" | |
| `unit/test_cedar_spike.py` (26) | Cedar behaviour spikes that do not use the mandate fact | the scenarios of design 6.2 that use `mandate_covers_booking` | |
| `integration/test_invariants.py` (9) | double booking, counters, slots, records without a user, two tickets, doctored audit (6) | I1 restated (a reservation needs a stored spoken confirmation whose hash matches the terms), I3 restated (a fee is only taken with a confirmation that covered it) | |
| `integration/test_write_pipeline.py` (18) | 17 | "step-up is signalled and stores nothing" becomes "a voice-guard refusal stores nothing and can be retried" | |
| `integration/test_fair_drop.py` (21), `test_waitlist.py` (23) | all except where a winner or a match is confirmed through the old path | the confirm steps use the new flow; hold lengths 30 minutes and 2 hours get their own tests | |
| `unit/store/test_keys_and_seed.py` (11) | keys of the other entities | mandate keys and seed expectations | mandate parts |

## Simulator, web, eval, red team

| File | Fate |
|---|---|
| `unit/simulator/test_personas.py`, `integration/test_simulator.py`, `unit/simulator/test_model.py` | personas read the sentence back, wait for the diner's turn and confirm with the hash; new behaviours `eager`, `wrong_hash`, `no_yes`; consent-link tests deleted |
| `integration/test_chat_web.py`, `unit/web/test_render_message.py`, `unit/web/test_steps_html.py` | keep the chat page and steps list; drop the consent-link rendering |
| `integration/test_telemetry_spans.py`, `unit/test_telemetry.py` | the allow-list of span attributes gets the new facts (no hash, no ids in spans); test run with a full booking is adapted |
| `integration/test_ablation.py`, `test_eval_run.py`, `unit/eval/*`, `tests/fixtures/eval_starter` | the ten starter tasks and the pinned numbers are rewritten after step 6; the 40-task set is regenerated |
| `redteam/test_redteam_suite.py`, `eval/redteam.py` | RT5 (party above the mandate must not be booked silently) becomes "a confirm without the read-back hash or too soon is refused"; the rest stay; one new attack (a confirm that names the terms of another hold) |
| `integration/test_compose_smoke.py` (`-m docker`) | the chat booking with approval on the consent page becomes a spoken-confirmation booking |

## AWS and infrastructure

| File | Fate |
|---|---|
| `aws/test_demo_flow.py` | Bob's step-up with the consent page becomes a spoken confirmation; the owner console test stays |
| `aws/test_runtime_smoke.py`, `aws/test_gateway.py`, `aws/test_gateway_policy.py` | tool list is seven tools; the hold-confirm-cancel run passes the guards; the Gateway read policy no longer names `mandate_status` |
| `aws/test_real_model.py` | the real-model booking must now read back and pass the hash; it measures whether the model does so |
| `unit/infra/test_gateway_policies.py`, `test_cdk_table.py` | the G1 policy loses `mandate_status`; template tests unaffected otherwise; `MCP_STATELESS` default |
| `integration/test_server_stateless.py`, `test_server_http.py`, `test_alexa_client_compat.py` | tool counts (8 to 7); the stateful-limit test changes when stateless becomes the default |

## Order consequence
Rewrite or delete a group only in the step that removes its code (steps 2 to 5 of the plan); the suite is run whole at the end of each step. Nothing is deleted before the replacement behaviour is tested.

## Decisions this list raises
- The engine's `step_up` decision kind is used by no rule after this change. Proposal: remove it and its pipeline path (`StepUpRequired`) in step 5 if nothing else uses it; keep it if removing it is not clean.
- `test_consent_web.py` may hold the only tests of the web session, login and CSRF code that the chat page and the owner console still use; those move to a new file before the rest is deleted.
