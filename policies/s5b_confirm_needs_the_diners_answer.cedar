// D-051: the diner needs a moment to hear the terms and answer. A confirm that arrives before the
// minimum pause (3 s, 6 s with a fee) cannot have followed an answer.
@id("S5b_confirm_needs_the_diners_answer") @on_deny("deny")
forbid (principal, action in [Action::"reservation_confirm", Action::"reservation_manage"], resource)
when { context.read_back_required && context.read_back_matches && !context.pause_elapsed };
