# One image for every FairTable service (server, dev issuer, web pages, seed script).
# The base image is pinned by tag and digest so a fresh clone builds the same thing until the end of judging.
FROM python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The source stays in /app (an editable install) because the Cedar policies in policies/ are found
# relative to the code. Dependencies come from pyproject.toml (exact versions) and constraints.txt (every package they pull in).
COPY pyproject.toml constraints.txt README.md LICENSE ./
COPY server ./server
COPY devauth ./devauth
COPY web ./web
COPY simulator ./simulator
COPY eval ./eval
COPY policies ./policies
COPY scripts ./scripts
RUN pip install -c constraints.txt -e ".[web,sim]"

RUN useradd --system --uid 10001 --no-create-home fairtable
USER fairtable

# python -m server (MCP, 8000) | python -m devauth (9000) | python -m web (8080); see docker-compose.yml
CMD ["python", "-m", "server"]
