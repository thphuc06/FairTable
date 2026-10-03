# policies/

Cedar policies, one rule per file, flat directory. The loader groups files by prefix and maps `cedarpy` reasons back to rules by the `@id` / `@on_deny` annotations, never by position.

| Prefix | Enforcement point | Rules | State |
|---|---|---|---|
| `p*`, `s*` | PEP-2 (stateful: counters and the read-back facts) | `P0_base`, `S1_max_active_holds`, `S2_agent_share_of_covers`, `S4_drop_slots_via_waitlist`, `S5a_confirm_needs_read_back`, `S5b_confirm_needs_the_diners_answer`, `S5c_confirm_needs_an_explicit_yes`, `S6_one_booking_per_restaurant_day` | Present. S6 (D-066) refuses a hold when the diner already has a confirmed table at that restaurant that day; the confirm transaction enforces the same under concurrency. S5a-c are the spoken-confirmation rules of D-051 (they replaced S3 and S3b): a confirm, or a cancel that costs money, needs a read-back token that fits (a), a pause since it was handed over (b) and the assistant's statement that the diner said yes (c). S2 applies to `reservation_hold` only (D1). |
| `g*` | PEP-1 (stateless: claims and request shape) | `G1_reads_any_valid_jwt` · `G2_writes_need_user_and_scope` · `G3_party_size_max_10` · `G4_verified_agent_only` | Present (P1-3). G3 applies to every tool; G4 to the write tools only (D-017). |

**G4 must use the `has`-guard.** A naive `forbid … when { principal.agent_tier != "verified" }` errors on a token that lacks the claim, is skipped, and the permit wins. See design §6.1.

Evaluation order: PEP-1, then PEP-2. A matching `forbid` is a denial (there is no step-up any more, D-051). No matching permit means `POLICY_DENIED`.

On AWS, AgentCore Gateway Policy repeats G1–G4 as defense in depth. Those Gateway-side files will live under `infra/` because the Gateway generates its own Cedar schema. Both sets share one behavioural test suite.

## Schemas and loading

`pep1.cedarschema` and `pep2.cedarschema` describe the entities and context of each enforcement point. They are used only to validate the policy files at startup (a typo in an attribute name stops the server); requests are not validated against them. Every policy needs an `@id`; every `forbid` needs `@on_deny("deny")`. Code: `server/kernel/` (`engine.py` loads and evaluates, `guidance.py` turns denials into agent-facing errors). Behavioural scenarios for G1-G4 live in `tests/unit/kernel/pep1_scenarios.py` so the Gateway copy can reuse them (D5).
