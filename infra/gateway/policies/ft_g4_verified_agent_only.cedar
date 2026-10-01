// AgentCore Gateway policy G4. Writes only from a verified agent. The `hasTag` guard is essential:
// reading a tag that is not there is an error, and an error in a `forbid` would be skipped and let the permit win.
// A token without `agent_tier` (a machine token, a client the trigger does not know) is therefore refused.
forbid (
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"ft___reservation_hold",
    AgentCore::Action::"ft___reservation_confirm",
    AgentCore::Action::"ft___reservation_manage",
    AgentCore::Action::"ft___waitlist_watch"
  ],
  resource == AgentCore::Gateway::"__GATEWAY_ARN__"
)
unless {
  principal.hasTag("agent_tier") &&
  principal.getTag("agent_tier") == "verified"
};
