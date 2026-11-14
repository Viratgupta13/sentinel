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
