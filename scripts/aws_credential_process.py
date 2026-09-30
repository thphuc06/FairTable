"""Hand `aws login` credentials to boto3 without `awscrt` (boto3's login provider needs it).

Use it as a `credential_process` in a throw-away config file, so the real ~/.aws/config stays as it is
and boto3 refreshes the short-term credentials by itself:

    printf '[profile ft]\ncredential_process = python %s\n' "$PWD/scripts/aws_credential_process.py" > /tmp/ft-aws-config
    AWS_CONFIG_FILE=/tmp/ft-aws-config AWS_PROFILE=ft python -m pytest ...

The credentials are printed to stdout for boto3 only; nothing is written to disk.
"""

import os
import subprocess
import sys


def main() -> int:
    env = {k: v for k, v in os.environ.items() if k not in ("AWS_CONFIG_FILE", "AWS_PROFILE")}
    source = os.environ.get("FAIRTABLE_SOURCE_PROFILE", "default")
    result = subprocess.run(
        ["aws", "configure", "export-credentials", "--format", "process", "--profile", source],
        env=env, capture_output=True, text=True, check=False,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
