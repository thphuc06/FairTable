# infra/runtime/

The AgentCore Runtime deployment package (direct code deployment, no Docker, no ECR). Nothing here touches AWS.

```
python infra/runtime/build_zip.py            # -> dist/fairtable-runtime.zip (about 38 MB)
```

- `requirements.txt`: the exact dependency set of the server (76 packages, Linux, CPython 3.12), every one with a `manylinux aarch64` wheel. Regenerate it inside the pinned image and re-run the tests:
  `docker run --rm -v <dir>:/w python:3.12.14-slim python /w/resolve.py` where `resolve.py` runs `pip install --dry-run --report` for the core dependencies of `pyproject.toml` and writes `name==version` lines.
- `build_zip.py`: downloads those wheels for aarch64, adds `server/`, `policies/` and `runtime_entry.py`, and writes a deterministic zip (modes 644/755, no bytecode, 250 MB / 750 MB limits). Tests: `tests/unit/infra/`.
- `../../runtime_entry.py`: the entry point. Runtime needs an MCP server on `0.0.0.0:8000/mcp`, stateless (`MCP_STATELESS=true`, which is also the server's default in every profile). Everything account-specific comes from environment variables set on the runtime: `TABLE_NAME`, `AWS_REGION`, `AUTH_ISSUER`, `AUTH_JWKS_URL`, `AUTH_AUDIENCE_CLAIM=client_id`, `AUTH_AUDIENCE`, `SLOT_TOKEN_SECRET` (32+ characters, never the built-in one), `MCP_ALLOWED_HOSTS`, `CONSENT_BASE_URL`.

Run the package the way Runtime does (arm64 emulation, needs the compose stack for the database and the issuer): unpack the zip to `/var/task` in `python:3.12.14-slim` started with `--platform linux/arm64` and run `python runtime_entry.py`. What this proves and what it does not: `docs/PLAN.md` section 3a, "second pass".
