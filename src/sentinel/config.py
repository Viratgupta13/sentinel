"""Runtime configuration, loaded from env vars / .env (prefix SENTINEL_)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENTINEL_",
        env_file=".env",
        extra="ignore",
    )

    # --- Provider ---
    # "anthropic" (default, first-party API) or "openai": any OpenAI-compatible
    # endpoint (Groq, Google AI Studio, OpenRouter - all have free tiers), handy
    # for zero-cost testing. With provider="openai", also override the three
    # model names below to ones that endpoint serves.
    provider: str = "anthropic"
    openai_base_url: str = "https://api.groq.com/openai/v1"
    openai_api_key: str | None = None

    # Tiered routing: cheap model triages every hunk, strong model reviews the risky ones.
    triage_model: str = "claude-haiku-5-5"
    review_model: str = "claude-opus-5-5"
    # Reserved for Phase 2 (decision-memory extraction over PR history).
    extraction_model: str = "claude-sonnet-5-5"

    triage_effort: str = "low"
    review_effort: str = "high"

    # Risk score (0-10) at or above which a hunk is escalated to deep review.
    risk_threshold: int = 4
    # Hard cap on deep-reviewed hunks per PR (cost guard).
    max_review_hunks: int = 12
    # Hunks per triage batch call.
    triage_batch_size: int = 16

    # Safety rails for very large PRs.
    max_diff_bytes: int = 400_000
    max_hunk_chars: int = 4_000

    github_token: str | None = None

    # --- Phase 2: decision memory ---
    # Where per-repo memory DBs live (expanded with ~).
    memory_home: str = "~/.sentinel"
    # How many merged PRs `sentinel memory build` harvests by default.
    harvest_limit: int = 200
    # Max review comments per PR fed to the extractor.
    harvest_max_comments: int = 30
    # Decisions below this confidence are never stored.
    min_decision_confidence: float = 0.5
    # How many memories are retrieved per deep-reviewed hunk.
    retrieve_top_k: int = 3

    # --- Phase 5: webhook server ---
    # HMAC secret for GitHub webhook signature verification (X-Hub-Signature-256).
    # Unset => unsigned payloads are accepted (local testing only; always set in prod).
    webhook_secret: str | None = None
    # Post (and keep updated) a review comment on the PR after each webhook review.
    post_comments: bool = True

    # --- Phase 6: hosted hub (GitHub App + "Sign in with GitHub") ---
    # Public URL this instance is served at (OAuth callback = <base_url>/auth/callback).
    base_url: str = "http://localhost:8787"
    # GitHub App credentials: reviews run with short-lived installation tokens,
    # so installed private repos work without any user PAT.
    github_app_id: str | None = None
    github_app_private_key: str | None = None  # PEM text ("\n" escapes accepted)
    github_app_private_key_path: str | None = None
    # OAuth ("Sign in with GitHub") - the GitHub App's own client id/secret.
    github_client_id: str | None = None
    github_client_secret: str | None = None
    # Signs login session cookies; any long random string. Login is enabled
    # only when client id + secret + this are all set.
    session_secret: str | None = None

    @property
    def login_enabled(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret and self.session_secret)


def load_settings() -> Settings:
    return Settings()
