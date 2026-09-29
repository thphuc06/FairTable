@id("S3_confirm_needs_mandate") @on_deny("step_up")
forbid (principal, action == Action::"reservation_confirm", resource)
unless { context.mandate_covers_booking };
