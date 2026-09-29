// PEP-1, stateless. Large groups must call the restaurant. `party_size` is 0 for tools without one.
@id("G3_party_size_max_10") @on_deny("deny")
forbid (principal, action, resource)
when { context.party_size > 10 };
