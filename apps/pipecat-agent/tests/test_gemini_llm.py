"""Tests for the Gemini 2.5 Flash adapter."""
from __future__ import annotations

import json

import httpx
import pytest

from voice_agent.gemini_llm import (
    DEFAULT_MODEL,
    GEMINI_BASE,
    GeminiError,
    GeminiResponse,
    _build_payload,
    _parse_response,
    _parse_sse_line,
    generate,
    make_llm_for_slot_extractor,
    stream_generate,
)


def test_build_payload_sets_system_and_user_messages():
    payload = _build_payload(system_message="be Priya", user_message="hi")
    assert payload["systemInstruction"]["parts"][0]["text"] == "be Priya"
    assert payload["contents"][0]["parts"][0]["text"] == "hi"
    assert payload["contents"][0]["role"] == "user"
    # Default generation config should be present.
    assert payload["generationConfig"]["maxOutputTokens"] == 1000


def test_build_payload_merges_custom_config():
    payload = _build_payload(
        system_message="x", user_message="y",
        generation_config={"temperature": 0.1, "maxOutputTokens": 50},
    )
    assert payload["generationConfig"]["temperature"] == 0.1
    assert payload["generationConfig"]["maxOutputTokens"] == 50


def test_parse_response_extracts_text_and_tokens():
    res = _parse_response(
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Haan ji"}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 120,
                "candidatesTokenCount": 8,
            },
        }
    )
    assert res.text == "Haan ji"
    assert res.finish_reason == "STOP"
    assert res.prompt_tokens == 120
    assert res.output_tokens == 8


def test_parse_response_raises_when_no_candidates():
    with pytest.raises(GeminiError, match="no candidates"):
        _parse_response({"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}})


def test_parse_response_concatenates_multipart_text():
    res = _parse_response(
        {
            "candidates": [
                {"content": {"parts": [{"text": "Haan "}, {"text": "ji."}]}}
            ]
        }
    )
    assert res.text == "Haan ji."


def test_parse_sse_line_returns_text():
    line = "data: " + json.dumps(
        {"candidates": [{"content": {"parts": [{"text": "chunk"}]}}]}
    )
    assert _parse_sse_line(line) == "chunk"


def test_parse_sse_line_ignores_non_data_lines():
    assert _parse_sse_line("") is None
    assert _parse_sse_line(":heartbeat") is None
    assert _parse_sse_line("data: [DONE]") is None


@pytest.mark.asyncio
async def test_generate_posts_to_correct_url_and_parses():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "Theek hai"}]}}],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await generate(
            system_message="be Priya",
            user_message="hello",
            api_key="g_test",
            client=client,
        )

    assert f"{GEMINI_BASE}/{DEFAULT_MODEL}:generateContent" in captured["url"]
    assert "key=g_test" in captured["url"]
    assert captured["body"]["systemInstruction"]["parts"][0]["text"] == "be Priya"
    assert res.text == "Theek hai"
    assert res.prompt_tokens == 5


@pytest.mark.asyncio
async def test_generate_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(GeminiError, match="500"):
            await generate(
                system_message="x", user_message="y", api_key="g", client=client
            )


@pytest.mark.asyncio
async def test_generate_rejects_missing_key():
    with pytest.raises(GeminiError, match="missing"):
        await generate(system_message="x", user_message="y", api_key="")


@pytest.mark.asyncio
async def test_make_llm_for_slot_extractor_uses_low_temperature():
    captured_body = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        # We patch the module's default client by using a monkeypatched generate via
        # passing client= through the closure. Easier: just inject via env-style:
        # build the closure then call it; internally generate() uses its own client.
        # So we test the closure indirectly: replace generate() temporarily.
        from voice_agent import gemini_llm as g

        original = g.generate

        async def fake_generate(*, system_message, user_message, api_key, model=None, generation_config=None, client=None, timeout=None):
            captured_body["temperature"] = generation_config["temperature"]
            captured_body["max"] = generation_config["maxOutputTokens"]
            return GeminiResponse(text="{}", finish_reason="STOP", prompt_tokens=1, output_tokens=1)

        g.generate = fake_generate  # type: ignore[assignment]
        try:
            llm = make_llm_for_slot_extractor(api_key="g_test")
            out = await llm("extract this please")
        finally:
            g.generate = original  # type: ignore[assignment]

    assert out == "{}"
    assert captured_body["temperature"] == 0.1
    assert captured_body["max"] == 600
