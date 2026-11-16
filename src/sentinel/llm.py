"""Anthropic client wrapper: structured-output calls, usage ledger, per-PR cost accounting."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from sentinel.models import CostLine

log = logging.getLogger("sentinel.llm")

T = TypeVar("T", bound=BaseModel)

# Longest a 429 is waited out (once) before surfacing the error.
MAX_RATE_LIMIT_WAIT_S = 20.0


class SentinelLLMError(RuntimeError):
    """Raised when a model call cannot produce a usable result."""


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float  # ~1.25x input


# Anthropic first-party API prices (USD/MTok). Update alongside model upgrades.
PRICING: dict[str, ModelPrice] = {
    "claude-haiku-5-5": ModelPrice(input=0.10, output=0.50, cache_read=0.01, cache_write=0.125),
    "claude-sonnet-5-5": ModelPrice(input=2.00, output=10.00, cache_read=0.20, cache_write=2.50),
    "claude-opus-5-5": ModelPrice(input=4.00, output=20.00, cache_read=0.20, cache_write=5.00),
    "claude-fable-5-1": ModelPrice(input=10.00, output=50.00, cache_read=0.25, cache_write=12.50),
}


@dataclass
class _ModelUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class UsageLedger:
    """Accumulates token usage per model and prices it."""

    usage: dict[str, _ModelUsage] = field(default_factory=dict)

    def record(self, model: str, response_usage: Any) -> None:
        entry = self.usage.setdefault(model, _ModelUsage())
        entry.calls += 1
        entry.input_tokens += getattr(response_usage, "input_tokens", 0) or 0
        entry.output_tokens += getattr(response_usage, "output_tokens", 0) or 0
        entry.cache_read_tokens += getattr(response_usage, "cache_read_input_tokens", 0) or 0
        entry.cache_write_tokens += getattr(response_usage, "cache_creation_input_tokens", 0) or 0

    @staticmethod
    def price_tokens(
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read: int = 0,
        cache_write: int = 0,
    ) -> float:
        price = PRICING.get(model)
        if price is None:
            return 0.0
        return (
            input_tokens * price.input
            + output_tokens * price.output
            + cache_read * price.cache_read
            + cache_write * price.cache_write
        ) / 1_000_000

    def cost_lines(self) -> list[CostLine]:
        lines: list[CostLine] = []
        for model, u in sorted(self.usage.items()):
            lines.append(
                CostLine(
                    model=model,
                    calls=u.calls,
                    input_tokens=u.input_tokens,
                    output_tokens=u.output_tokens,
                    cache_read_tokens=u.cache_read_tokens,
                    cache_write_tokens=u.cache_write_tokens,
                    cost_usd=self.price_tokens(
                        model,
                        u.input_tokens,
                        u.output_tokens,
                        u.cache_read_tokens,
                        u.cache_write_tokens,
                    ),
                )
            )
        return lines

    def total_cost(self) -> float:
        return sum(line.cost_usd for line in self.cost_lines())


def _system_text(system: str | list[dict[str, Any]]) -> str:
    """Flatten Anthropic-style system blocks to plain text (OpenAI-compat path)."""
    if isinstance(system, str):
        return system
    return "\n\n".join(block.get("text", "") for block in system)


def _strip_fences(text: str) -> str:
    """Some OpenAI-compatible models wrap JSON in ```json fences despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


class LLMClient:
    """Structured-output LLM calls: Anthropic SDK by default, or any
    OpenAI-compatible endpoint (Groq/Gemini/OpenRouter free tiers) when
    settings.provider == "openai"."""

    def __init__(self, ledger: UsageLedger | None = None, settings: Any = None) -> None:
        self.ledger = ledger or UsageLedger()
        self._settings = settings
        self._provider = getattr(settings, "provider", "anthropic") if settings else "anthropic"
        # Only construct the Anthropic client when it will be used (it requires a key).
        self._client = anthropic.Anthropic(max_retries=3) if self._provider == "anthropic" else None

    def structured(
        self,
        *,
        model: str,
        system: str | list[dict[str, Any]],
        user_content: str,
        schema: dict[str, Any],
        output_model: type[T],
        effort: str = "high",
        max_tokens: int = 16000,
    ) -> T:
        """One structured-output call: JSON-schema constrained, validated with Pydantic."""
        if self._provider != "anthropic":
            return self._structured_openai_compat(
                model=model,
                system=system,
                user_content=user_content,
                schema=schema,
                output_model=output_model,
                max_tokens=max_tokens,
            )
        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
                output_config={
                    "effort": effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except anthropic.AuthenticationError as e:
            raise SentinelLLMError(
                "Anthropic authentication failed. Set ANTHROPIC_API_KEY (see .env.example)."
            ) from e
        except anthropic.RateLimitError as e:
            raise SentinelLLMError("Rate limited by the Anthropic API; re-run shortly.") from e
        except anthropic.APIStatusError as e:
            raise SentinelLLMError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise SentinelLLMError("Network error reaching the Anthropic API.") from e

        self.ledger.record(model, response.usage)

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            explanation = getattr(details, "explanation", "") if details else ""
            raise SentinelLLMError(f"Model declined the request: {explanation or 'refusal'}")
        if response.stop_reason == "max_tokens":
            raise SentinelLLMError(
                f"Hit max_tokens={max_tokens} on {model}; raise the limit or shrink the input."
            )

        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise SentinelLLMError(f"No text block in {model} response.")
        try:
            return output_model.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as e:
            log.debug("Invalid structured output from %s: %s", model, text[:500])
            raise SentinelLLMError(f"Invalid structured output from {model}: {e}") from e

    def _structured_openai_compat(
        self,
        *,
        model: str,
        system: str | list[dict[str, Any]],
        user_content: str,
        schema: dict[str, Any],
        output_model: type[T],
        max_tokens: int,
    ) -> T:
        """Same contract via an OpenAI-compatible /chat/completions endpoint.

        No native json_schema constraint is assumed (support varies across free
        providers): the schema goes into the system prompt, `json_object` mode is
        requested when supported, and Pydantic validation stays the gate either way.
        """
        import httpx

        s = self._settings
        if not getattr(s, "openai_api_key", None):
            raise SentinelLLMError(
                "SENTINEL_PROVIDER=openai but SENTINEL_OPENAI_API_KEY is not set "
                "(see .env.example)."
            )
        sys_text = (
            _system_text(system)
            + "\n\nRespond with a single JSON object that matches this JSON schema "
            + "exactly. No markdown fences, no prose outside the JSON.\nSchema:\n"
            + json.dumps(schema)
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_text},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        url = s.openai_base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {s.openai_api_key}"}

        data: dict[str, Any] | None = None
        format_fallback_used = rate_wait_used = False
        for _attempt in range(3):
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=180)
            except httpx.HTTPError as e:
                raise SentinelLLMError(f"Network error reaching {url}: {e}") from e
            if (
                resp.status_code == 400
                and not format_fallback_used
                and "response_format" in payload
            ):
                # Some free endpoints reject json_object mode; prompt-only JSON then.
                payload.pop("response_format")
                format_fallback_used = True
                continue
            if resp.status_code == 401:
                raise SentinelLLMError(
                    f"Authentication failed at {s.openai_base_url} - check "
                    "SENTINEL_OPENAI_API_KEY."
                )
            if resp.status_code == 429 and not rate_wait_used:
                # Per-minute token windows reset fast; one short wait usually clears it.
                try:
                    wait = float(resp.headers.get("retry-after", "10"))
                except ValueError:
                    wait = 10.0
                if wait <= MAX_RATE_LIMIT_WAIT_S:
                    log.info("rate limited by %s; retrying in %.1fs", s.openai_base_url, wait)
                    time.sleep(wait + 0.5)
                    rate_wait_used = True
                    continue
            if resp.status_code == 429:
                raise SentinelLLMError(
                    f"Rate limited by {s.openai_base_url} (free tiers are tight); "
                    "re-run shortly or lower --max-hunks."
                )
            if resp.status_code >= 400:
                raise SentinelLLMError(f"API error {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            break
        assert data is not None  # loop always breaks or raises

        usage = data.get("usage") or {}
        self.ledger.record(
            model,
            _ModelUsage(
                input_tokens=usage.get("prompt_tokens", 0) or 0,
                output_tokens=usage.get("completion_tokens", 0) or 0,
            ),
        )

        choice = (data.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise SentinelLLMError(
                f"Hit max_tokens={max_tokens} on {model}; raise the limit or shrink the input."
            )
        text = (choice.get("message") or {}).get("content")
        if not text:
            raise SentinelLLMError(f"No text content in {model} response.")
        try:
            return output_model.model_validate(json.loads(_strip_fences(text)))
        except (json.JSONDecodeError, ValidationError) as e:
            log.debug("Invalid structured output from %s: %s", model, text[:500])
            raise SentinelLLMError(f"Invalid structured output from {model}: {e}") from e
