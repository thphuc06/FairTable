// AgentCore Gateway policy G3 (part 2 of 3): the same limit at search time.
forbid (
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"ft___restaurant_search",
  resource == AgentCore::Gateway::"__GATEWAY_ARN__"
)
when {
  context.input has party_size &&
  context.input.party_size > 10
};
