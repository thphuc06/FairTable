// AgentCore Gateway policy G3 (part 3 of 3): the same limit for a standing watch.
// reservation_hold, reservation_confirm and reservation_manage take a slot token or an id, not a party size,
// so for them the limit stays with the server (rule G3 in policies/g3_*.cedar).
forbid (
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"ft___waitlist_watch",
  resource == AgentCore::Gateway::"__GATEWAY_ARN__"
)
when {
  context.input has party_size &&
  context.input.party_size > 10
};
