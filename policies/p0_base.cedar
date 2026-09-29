@id("P0_base")
permit (
  principal is Diner,
  action in [Action::"reservation_hold", Action::"reservation_confirm",
             Action::"reservation_manage", Action::"waitlist_watch"],
  resource is Venue
)
when { context.agent_tier == "verified" };
