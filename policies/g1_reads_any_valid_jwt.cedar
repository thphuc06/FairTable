// PEP-1, stateless. Read tools: any caller with a valid JWT (the verifier already ran).
@id("G1_reads_any_valid_jwt")
permit (
  principal is Client,
  action in [Action::"restaurant_search", Action::"availability_check",
             Action::"mandate_status", Action::"waitlist_status"],
  resource is Service
);
