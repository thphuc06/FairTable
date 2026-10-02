// D-051: a booking, or a cancellation that costs money, needs the terms to have been read back to the diner.
// The assistant proves it with the read-back token the server handed out for exactly these terms.
// read_back_required is true for a confirm and for a cancel with a fee, false for every other call.
@id("S5a_confirm_needs_read_back") @on_deny("deny")
forbid (principal, action in [Action::"reservation_confirm", Action::"reservation_manage"], resource)
when { context.read_back_required && !context.read_back_matches };
