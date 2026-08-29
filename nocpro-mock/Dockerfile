FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /bin/
WORKDIR /workspace/nocpro-mock
COPY nocpro-mock/pyproject.toml nocpro-mock/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY nocpro-mock/src ./src
COPY nocpro-chain-explain/contracts /workspace/nocpro-chain-explain/contracts
RUN uv sync --frozen --no-dev
ENTRYPOINT []
