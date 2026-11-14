FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

# ANTHROPIC_API_KEY and GITHUB_TOKEN are injected at runtime:
#   docker run -e ANTHROPIC_API_KEY -e GITHUB_TOKEN sentinel review <pr-url>
ENTRYPOINT ["sentinel"]
CMD ["--help"]
