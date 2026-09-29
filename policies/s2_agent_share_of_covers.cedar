// Verbatim from design §6.2. Open question D1 (docs/PLAN.md): waitlist_watch may be removed from this list.
@id("S2_agent_share_of_covers") @on_deny("deny")
forbid (principal, action in [Action::"reservation_hold", Action::"waitlist_watch"], resource)
when { context.agent_covers_booked + context.party_size > resource.agent_cover_cap };
