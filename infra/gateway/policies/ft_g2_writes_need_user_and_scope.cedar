// AgentCore Gateway policy G2. Write tools: a real user (the token has `username`) and the scope
// `fairtable/book`. Every JWT claim is a string tag; `scope` holds several values, so match with `like`.
// A machine token has no `username` tag and never matches.
permit (
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"ft___reservation_hold",
    AgentCore::Action::"ft___reservation_confirm",
    AgentCore::Action::"ft___reservation_manage",
    AgentCore::Action::"ft___waitlist_watch"
  ],
  resource == AgentCore::Gateway::"__GATEWAY_ARN__"
)
when {
  principal.hasTag("username") &&
  principal.hasTag("scope") &&
  principal.getTag("scope") like "*fairtable/book*"
};
