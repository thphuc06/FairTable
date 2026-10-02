// D-051: the assistant must state that the diner said yes (user_confirmed). The server cannot hear
// the diner; the claim is stored with the booking so that it can be audited.
@id("S5c_confirm_needs_an_explicit_yes") @on_deny("deny")
forbid (principal, action in [Action::"reservation_confirm", Action::"reservation_manage"], resource)
when { context.read_back_required && !context.user_confirmed };
