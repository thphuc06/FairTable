@id("S1_max_active_holds") @on_deny("deny")
forbid (principal, action == Action::"reservation_hold", resource)
when { context.active_holds_user_venue >= 2 };
