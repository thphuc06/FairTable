@id("S4_drop_slots_via_waitlist") @on_deny("deny")
forbid (principal, action == Action::"reservation_hold", resource)
when { context.slot_is_drop_controlled };
