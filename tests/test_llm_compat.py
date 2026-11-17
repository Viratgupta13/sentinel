"""OpenAI-compatible provider path: parsing, fences, usage recording (httpx mocked)."""

import httpx
import pytest
from pydantic import BaseModel

from sentinel.config import Settings
from sentinel.llm import LLMClient, SentinelLLMError, _strip_fences, _system_text


class _Out(BaseModel):
    answer: str


_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def _settings() -> Settings:
    return Settings(
        provider="openai",
        openai_base_url="https://fake.example/v1",
        openai_api_key="test-key",
        _env_file=None,
    )


def _fake_response(content: str, status: int = 200, finish: str = "stop") -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        },
        request=httpx.Request("POST", "https://fake.example/v1/chat/completions"),
    )


def test_strip_fences():
    assert _strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _strip_fences('{"a": 1}') == '{"a": 1}'


def test_system_text_flattens_blocks():
    blocks = [{"type": "text", "text": "one"}, {"type": "text", "text": "two"}]
    assert _system_text(blocks) == "one\n\ntwo"
    assert _system_text("plain") == "plain"


def test_openai_compat_parses_and_records(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: _fake_response('```json\n{"answer": "ok"}\n```')
    )
    client = LLMClient(settings=_settings())
    out = client.structured(
        model="test-model",
        system="sys",
        user_content="hi",
        schema=_SCHEMA,
        output_model=_Out,
    )
    assert out.answer == "ok"
    line = client.ledger.cost_lines()[0]
    assert line.input_tokens == 100 and line.output_tokens == 20
    assert line.cost_usd == 0.0  # unknown model -> unpriced


def test_openai_compat_missing_key():
    settings = _settings()
    settings.openai_api_key = None
    client = LLMClient(settings=settings)
    with pytest.raises(SentinelLLMError, match="OPENAI_API_KEY"):
        client.structured(
            model="m", system="s", user_content="u", schema=_SCHEMA, output_model=_Out
        )


def test_openai_compat_truncation_raises(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _fake_response("{", finish="length"))
    client = LLMClient(settings=_settings())
    with pytest.raises(SentinelLLMError, match="max_tokens"):
        client.structured(
            model="m", system="s", user_content="u", schema=_SCHEMA, output_model=_Out
        )


def _rate_limited(retry_after: str) -> httpx.Response:
    return httpx.Response(
        429, headers={"retry-after": retry_after}, json={"error": "rate"},
        request=httpx.Request("POST", "https://fake.example/v1/chat/completions"),
    )


def _call(client):
    return client.structured(
        model="m", system="s", user_content="u", schema=_SCHEMA, output_model=_Out,
    )


def test_rate_limit_short_wait_retries_once(monkeypatch):
    import sentinel.llm as llm_mod

    responses = [_rate_limited("2"), _fake_response('{"answer": "ok"}')]
    slept = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(llm_mod.time, "sleep", slept.append)
    assert _call(LLMClient(settings=_settings())).answer == "ok"
    assert slept == [2.5]


def test_rate_limit_long_wait_or_repeat_raises(monkeypatch):
    import sentinel.llm as llm_mod

    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _rate_limited("90"))
    with pytest.raises(SentinelLLMError, match="Rate limited"):  # too long to wait
        _call(LLMClient(settings=_settings()))

    calls = []

    def always_limited(*a, **k):
        calls.append(1)
        return _rate_limited("45")  # a per-minute window: worth waiting out

    monkeypatch.setattr(httpx, "post", always_limited)
    with pytest.raises(SentinelLLMError, match="Rate limited"):
        _call(LLMClient(settings=_settings()))
    assert len(calls) == llm_mod.MAX_RATE_LIMIT_RETRIES + 1
