// AgentCore Gateway policy G1 (defence in depth: the server enforces G1 as well, policies/g1_*.cedar).
// Read tools: any caller whose token the gateway accepted, bots included.
// `__GATEWAY_ARN__` is replaced by the infrastructure code with the gateway's ARN.
permit (
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"ft___restaurant_search",
    AgentCore::Action::"ft___availability_check",
    AgentCore::Action::"ft___mandate_status",
    AgentCore::Action::"ft___waitlist_status"
  ],
  resource == AgentCore::Gateway::"__GATEWAY_ARN__"
);
