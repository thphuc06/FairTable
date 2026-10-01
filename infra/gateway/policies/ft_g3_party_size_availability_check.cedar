// AgentCore Gateway policy G3 (part 1 of 3). Large groups must call the restaurant: refuse a party above 10.
// `party_size` is optional in the tool schema (it has a default), so it needs a `has` guard.
// One policy per tool: a condition on tool input cannot span tools whose inputs differ.
forbid (
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"ft___availability_check",
  resource == AgentCore::Gateway::"__GATEWAY_ARN__"
)
when {
  context.input has party_size &&
  context.input.party_size > 10
};
