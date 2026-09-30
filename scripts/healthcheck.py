"""Container health check: ``python scripts/healthcheck.py URL [--any-status]``.

Exit 0 when the URL answers with a 2xx status; with ``--any-status`` any HTTP answer counts (the MCP
endpoint refuses a plain GET but that still proves the server is up). Standard library only.
"""

import sys
import urllib.error
import urllib.request


def main(argv: list[str]) -> int:
    url = argv[1]
    any_status = "--any-status" in argv[2:]
    try:
        urllib.request.urlopen(url, timeout=3)
    except urllib.error.HTTPError:
        return 0 if any_status else 1
    except OSError:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
