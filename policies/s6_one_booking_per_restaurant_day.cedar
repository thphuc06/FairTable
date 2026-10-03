// PEP-2, stateful (D-066). A diner holds one table per restaurant per day: a second booking the same day is
// almost always a mistake (the same request made twice, a change of mind that forgot the first table) and it takes
// a table from someone else. The caller works out `booked_same_day` from the diner's confirmed reservations; the
// final guarantee under concurrency is a conditional write at confirm time (BOOKED# marker).
@id("S6_one_booking_per_restaurant_day") @on_deny("deny")
forbid (principal, action == Action::"reservation_hold", resource)
when { context.booked_same_day };
