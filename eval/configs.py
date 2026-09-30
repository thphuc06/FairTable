"""The ablation configurations (design section 9.3), chosen by name; the same server code runs in all three.

| Config | What is different | What it shows |
|---|---|---|
| A0 | no policy layer (PEP-1 and PEP-2 allow everything) | the baseline: an "open store" |
| A1 | the full FairTable trust layer | the trust layer stops violations without blocking legitimate bookings |
| A2 | full rules, but no step-up: the assistant's own "yes" is enough | what the out-of-conversation approval adds |

A0 removes the *policy* layer only. The database's own atomic guards stay on in every configuration:
one live claim per table, and the counters behind rules S1 and S2 (they are written as DynamoDB
conditions so that races cannot exceed them). So A0 does not show S1 or S2 violations by design.
"""

from collections.abc import Callable

from server.kernel import TrustKernel

CONFIGS: dict[str, Callable[[], TrustKernel]] = {
    "A0": TrustKernel.open_store,
    "A1": TrustKernel.load,
    "A2": TrustKernel.without_step_up,
}


def kernel_for(config: str) -> TrustKernel:
    try:
        return CONFIGS[config]()
    except KeyError:
        raise ValueError(f"unknown configuration {config!r}; use one of {', '.join(CONFIGS)}") from None
