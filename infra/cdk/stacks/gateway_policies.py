"""The Cedar policies of the Gateway (plan task P2-6), read from `infra/gateway/policies/*.cedar`.

Pure Python (no CDK import), so the unit tests can load it. The files carry comments and a placeholder for the
gateway's ARN; `render` removes the comments and fills the placeholder in, which gives the statement that goes into
`AWS::BedrockAgentCore::Policy`.
"""

import re
from pathlib import Path

POLICY_DIR = Path(__file__).resolve().parents[2] / "gateway" / "policies"
PLACEHOLDER = "__GATEWAY_ARN__"
MIN_STATEMENT_CHARS, MAX_STATEMENT_CHARS = 35, 10_000  # limits of the service (the Policy guide)
NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,47}")  # engine and policy names: letters, digits, underscore


def is_permit(text: str) -> bool:
    """True for a `permit` policy (the first statement line that is not a comment)."""
    first = next(ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("//"))
    return first.startswith("permit")


def policy_files(*, permits_only: bool = False) -> dict[str, str]:
    """Policy name (the file name without `.cedar`) -> the file's text, in a fixed order."""
    files = {p.stem: p.read_text(encoding="utf-8") for p in sorted(POLICY_DIR.glob("*.cedar"))}
    return {n: t for n, t in files.items() if is_permit(t)} if permits_only else files


def render(text: str, gateway_arn: str) -> str:
    """Drop the comment lines and blank lines, fill in the gateway ARN."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("//")]
    body = "\n".join(lines)
    if PLACEHOLDER not in body:
        raise ValueError("a gateway policy must name the gateway with the placeholder")
    return body.replace(PLACEHOLDER, gateway_arn)
