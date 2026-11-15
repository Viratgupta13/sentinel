FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir ".[server]"

# Secrets (ANTHROPIC_API_KEY / SENTINEL_*) are injected at runtime.
# Default: run the hub server. For one-off CLI use:
#   docker run sentinel-img sentinel review <pr-url>
EXPOSE 8000
CMD ["sh", "-c", "sentinel serve --host 0.0.0.0 --port ${PORT:-8000}"]
