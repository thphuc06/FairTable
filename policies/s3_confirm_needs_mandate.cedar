// Verbatim from design §6.2. Open question D2 (docs/PLAN.md): an S3b rule for cancel-with-fee may be added.
@id("S3_confirm_needs_mandate") @on_deny("step_up")
forbid (principal, action == Action::"reservation_confirm", resource)
unless { context.mandate_covers_booking };
