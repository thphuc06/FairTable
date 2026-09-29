# policies/

Cedar policies, one rule per file, flat directory. The loader groups files by prefix and maps `cedarpy` reasons back to rules by the `@id` / `@on_deny` annotations, never by position.

| Prefix | Enforcement point | Rules | State |
|---|---|---|---|
| `p*`, `s*` | PEP-2 (stateful: counters and mandate from DynamoDB) | `P0_base`, `S1_max_active_holds`, `S2_agent_share_of_covers`, `S3_confirm_needs_mandate`, `S4_drop_slots_via_waitlist` | Present. Text is verbatim from the design (§6.2), pending open questions D1 (S2 action list) and D2 (S3b). |
| `g*` | PEP-1 (stateless: claims and request shape) | `G1` reads: any valid JWT · `G2` writes: principal has `username` and scope `fairtable/book` · `G3` forbid `party_size > 10` · `G4` forbid unless `principal has agent_tier && principal.agent_tier == "verified"` | To be written in plan task P1-3, together with its tests. |

**G4 must use the `has`-guard.** A naive `forbid … when { principal.agent_tier != "verified" }` errors on a token that lacks the claim, is skipped, and the permit wins. See design §6.1.

Evaluation order: PEP-1, then PEP-2. Priority: deny > step_up > allow. No matching permit means `POLICY_DENIED`.

On AWS, AgentCore Gateway Policy repeats G1–G4 as defense in depth. Those Gateway-side files will live under `infra/` because the Gateway generates its own Cedar schema. Both sets share one behavioural test suite.
