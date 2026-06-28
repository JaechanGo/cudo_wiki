"""GLM(LiteLLM) 리랭크 클라이언트 — httpx AsyncClient 래퍼 (plan §5.1).

★ base/key 는 Settings 경유(하드코딩 금지). non-200 은 raise_for_status() 로 HTTPStatusError 를
올려 rerank 폴백을 보장한다(minor-2). LLM 은 순위(인덱스 배열 JSON)만 출력 — 조번호/본문 생성 금지.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

import httpx

from app.common.config import get_settings

# 운영 합의 전 기본 모델명(Settings/상수, R-6). 폴백이 항상 동작하므로 미확정이 가용성 위협 안 함.
GLM_MODEL: str = "glm-5.2"

_SYSTEM_PROMPT = (
    "너는 사내 규정 검색 리랭커다. 주어진 후보들을 질의 관련도가 높은 순서로 재정렬해 "
    "후보 인덱스 배열 JSON 만 출력한다. 예: [2, 0, 1]. 다른 설명은 출력하지 마라."
)

_JSON_ARRAY_RE = re.compile(r"\[[\s\d,]*\]")


class RerankClient(Protocol):
    """리랭크 client 계약 — 후보 인덱스 순위 리스트 반환."""

    async def rank(self, query: str, candidates: list[str]) -> list[int]: ...


def parse_order(content: str) -> list[int]:
    """LLM 응답 문자열에서 인덱스 배열 JSON 을 파싱한다. 실패 시 ValueError."""
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        match = _JSON_ARRAY_RE.search(content or "")
        if match is None:
            raise ValueError("리랭크 응답에서 인덱스 배열을 찾지 못함") from None
        parsed = json.loads(match.group())
    if not isinstance(parsed, list) or not all(isinstance(x, int) for x in parsed):
        raise ValueError("리랭크 응답이 정수 인덱스 배열이 아님")
    return parsed


class GlmClient:
    """LiteLLM(OpenAI 호환) chat.completions 로 리랭크 순위를 받는 비동기 client."""

    def __init__(
        self,
        *,
        base: str | None = None,
        api_key: str | None = None,
        model: str = GLM_MODEL,
        timeout_s: float = 8.0,
    ) -> None:
        settings = get_settings()
        self._base = (base or settings.litellm_base).rstrip("/")
        self._key = api_key if api_key is not None else settings.litellm_key_glm
        self._model = model
        self._timeout = timeout_s

    async def rank(self, query: str, candidates: list[str]) -> list[int]:
        """질의와 (레닥션된) 후보 본문으로 GLM 을 호출해 인덱스 순위를 반환한다."""
        numbered = "\n".join(f"[{i}] {body}" for i, body in enumerate(candidates))
        payload = {
            "model": self._model,
            "temperature": 0,
            "max_tokens": 512,  # 추론 토큰 잠식 대비 방어선(enable_thinking:false 가 1차 해법)
            # GLM-5.2 는 추론모델 — 추론을 비활성화해야 content 에 인덱스 배열이 즉시 채워짐
            # (reasoning_content 로 토큰이 새어 content='' 가 되지 않게). ADR-005 참조.
            # reasoning_effort:low(역효과)/thinking:{type:disabled}(무시) 는 미작동 — 채택 금지.
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"질의: {query}\n\n후보:\n{numbered}"},
            ],
        }
        headers = {"Authorization": f"Bearer {self._key}"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()  # non-200 → HTTPStatusError ⊂ httpx.HTTPError (폴백 보장)
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return parse_order(content)
