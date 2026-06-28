"""GlmClient.rank() payload 검증 — GLM-5.2 추론모델 대응(ADR-005).

추론 비활성(`chat_template_kwargs.enable_thinking=False`) + 넉넉한 `max_tokens=512` 가
실제 wire payload 에 실리는지 검증한다. 네트워크 0 — `httpx.MockTransport` 주입으로
요청 body 를 캡처(레포에 respx 미존재 → MockTransport+monkeypatch, plan §3.2).
실 키 미사용·미출력(더미 `api_key="test"`).
"""

from __future__ import annotations

import json

import httpx

from app.search.glm_client import GLM_MODEL, GlmClient


async def test_rank_payload_disables_thinking_and_widens_max_tokens(monkeypatch):
    """rank() 가 보내는 JSON body 에 추론 비활성 + max_tokens=512 + 불변 필드가 실린다."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("Authorization")
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "[0, 1]"}}]})

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        # GlmClient 내부의 httpx.AsyncClient(timeout=...) 에 MockTransport 를 강제 주입.
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)

    client = GlmClient(base="http://x/v1", api_key="test")
    order = await client.rank("연차 며칠?", ["연차휴가 규정", "출장비 정산"])

    # 성공 경로(파싱) 보존
    assert order == [0, 1]

    body = captured["body"]
    # ── 핵심: GLM-5.2 추론 비활성 + 방어선 max_tokens ──
    assert body["chat_template_kwargs"]["enable_thinking"] is False
    assert body["max_tokens"] == 512
    # ── 불변 필드 ──
    assert body["temperature"] == 0
    assert body["model"] == GLM_MODEL == "glm-5.2"
    assert captured["auth"] == "Bearer test"  # Authorization: Bearer 헤더 불변
    assert captured["url"] == "http://x/v1/chat/completions"
    # 미작동 옵션은 추가되지 않음(채택 금지)
    assert "reasoning_effort" not in body
    assert "thinking" not in body
