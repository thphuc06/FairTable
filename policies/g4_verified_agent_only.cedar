// PEP-1, stateless. Writes only from a verified agent. The `has`-guard is essential: a naive
// `when { principal.agent_tier != "verified" }` errors on a token without the claim, is skipped,
// and the permit wins (design section 6.1, tests/unit/kernel/test_pep1.py).
@id("G4_verified_agent_only") @on_deny("deny")
forbid (
  principal,
  action in [Action::"reservation_hold", Action::"reservation_confirm",
             Action::"reservation_manage", Action::"waitlist_watch"],
  resource
)
unless { principal has agent_tier && principal.agent_tier == "verified" };
