// D1 (docs/DECISIONS.md D-014): waitlist_watch is not covered here. A watch consumes no covers;
// S2 applies when a hold is created for the watcher.
@id("S2_agent_share_of_covers") @on_deny("deny")
forbid (principal, action == Action::"reservation_hold", resource)
when { context.agent_covers_booked + context.party_size > resource.agent_cover_cap };
