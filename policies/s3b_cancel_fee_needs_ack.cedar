// D2 (docs/DECISIONS.md D-014): cancelling with a fee needs explicit step-up consent.
// cancel_fee_cents is 0 for view / modify and for fee-free cancels, so only a real fee triggers this.
@id("S3b_cancel_fee_needs_ack") @on_deny("step_up")
forbid (principal, action == Action::"reservation_manage", resource)
when { context.cancel_fee_cents > 0 && !context.cancel_fee_acknowledged };
