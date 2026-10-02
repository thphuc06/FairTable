"""The offer book: where the offers behind the ids are kept (D-059). See ``server/domain/offers.py`` for the idea."""

from datetime import timedelta

from server.domain.clock import Clock, iso_z
from server.domain.errors import ErrorCode, FairTableError
from server.domain.offers import DEFAULT_TTL_S, SlotClaims, invalid, new_code, normalize
from server.store import Store, TransactionCancelled, TxOp, keys


def offer_item(code: str, claims: SlotClaims, now_iso: str, expires_iso: str, ttl_epoch: int) -> dict:
    key = keys.offer(code)
    return {
        "PK": key.pk, "SK": key.sk, "entity": "offer", "rid": claims.restaurant_id, "date": claims.date,
        "slot": claims.slot_key, "party": claims.party_size, "ver": claims.slot_ver, "sub": claims.sub,
        "hot": claims.hot, "drop": claims.drop_id, "created_at": now_iso, "expires_at": expires_iso,
        "ttl": ttl_epoch,  # DynamoDB removes old offers when its TTL is on; the expiry is always checked on read
    }


class OfferBook:
    def __init__(self, store: Store, clock: Clock, ttl_s: int = DEFAULT_TTL_S, make_code=new_code) -> None:
        if ttl_s <= 0:
            raise ValueError("ttl_s must be positive")
        self._store, self._clock, self._ttl_s, self._make_code = store, clock, ttl_s, make_code

    def issue_all(self, claims: list[SlotClaims]) -> list[str]:
        """One id per slot, written in one transaction (an id that already exists cancels it: new ids, once more)."""
        if not claims:
            return []
        now = self._clock.now()
        expires = now + timedelta(seconds=self._ttl_s)
        for attempt in range(2):
            codes = [self._make_code() for _ in claims]
            ops = [
                TxOp("Put", item=offer_item(code, c, iso_z(now), iso_z(expires), int(expires.timestamp()) + 3600),
                     condition="attribute_not_exists(PK)")
                for code, c in zip(codes, claims, strict=True)
            ]
            try:
                self._store.transact(ops)
                return codes
            except TransactionCancelled:
                if attempt:
                    raise
        raise AssertionError("unreachable")

    def issue(self, claims: SlotClaims) -> str:
        return self.issue_all([claims])[0]

    def verify(self, offer_id: object, *, sub: str) -> SlotClaims:
        """The claims behind an id, for the user it was shown to and before it expires. Never says which check failed."""
        code = normalize(offer_id)
        if code is None:
            raise invalid("malformed")
        item = self._store.get_item(keys.offer(code))
        if item is None:
            raise invalid("not_found")
        if iso_z(self._clock.now()) >= item["expires_at"]:
            raise FairTableError(
                ErrorCode.OFFER_EXPIRED,
                "That table offer has expired.",
                hint="Use an offer_id from a fresh availability result.",
                reason="expired",
            )
        if item["sub"] != sub:
            raise invalid("wrong_user")
        return SlotClaims(
            restaurant_id=item["rid"], date=item["date"], slot_key=item["slot"], party_size=int(item["party"]),
            slot_ver=int(item["ver"]), sub=item["sub"], hot=bool(item["hot"]), drop_id=item["drop"],
        )
