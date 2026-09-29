// PEP-1, stateless. Write tools: a real user (has `username`) and the `fairtable/book` scope.
// An M2M bot token has no `username`, so it can read but never write.
@id("G2_writes_need_user_and_scope")
permit (
  principal is Client,
  action in [Action::"reservation_hold", Action::"reservation_confirm",
             Action::"reservation_manage", Action::"waitlist_watch"],
  resource is Service
)
when { principal has username && principal.scopes.contains("fairtable/book") };
