FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY contracts ./contracts
COPY libs ./libs
COPY config ./config
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY services/analysis-worker ./services/analysis-worker
COPY services/api ./services/api
ENV PYTHONPATH=/app:/app/services/analysis-worker:/app/services/api
CMD [".venv/bin/uvicorn", "nocpro_api.app:app", "--app-dir", "services/api", "--host", "0.0.0.0", "--port", "8000"]
