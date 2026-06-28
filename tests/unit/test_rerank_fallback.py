"""rerank 단위테스트 — GLM mock 정상 + httpx 오류 폴백 + parse_error + 레닥션 강제.

네트워크 0 (client 주입). plan §5.2/§9.4.
"""

from __future__ import annotations

import httpx
import pytest

from app.search.rerank import rerank
from app.search.types import SearchHit


def _hit(i: int, body: str = "본문", score: float = 1.0) -> SearchHit:
    return SearchHit(
        chunk_id=i, chunk_class="clause", board_id=1, body=body,
        score=score, raw_score=score, canonical_clause_id=f"C#{i}",
        canonical_authority_id=None, clause_label=None, source_post_id=None,
        clause_id=i, source_attachment_id=None, authority_id=None,
        posted_at=None, meta=None,
    )


class FakeClient:
    """후보를 역순으로 재정렬하는 정상 client."""

    def __init__(self) -> None:
        self.received: list[str] | None = None

    async def rank(self, query: str, candidates: list[str]) -> list[int]:
        self.received = candidates
        return list(range(len(candidates) - 1, -1, -1))


class RaisingClient:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def rank(self, query: str, candidates: list[str]) -> list[int]:
        raise self._exc


class BadOrderClient:
    """범위 초과 인덱스 반환 → parse_error 유발."""

    async def rank(self, query: str, candidates: list[str]) -> list[int]:
        return [99]


async def test_rerank_normal_reorders():
    hits = [_hit(0, score=3.0), _hit(1, score=2.0), _hit(2, score=1.0)]
    client = FakeClient()
    res = await rerank("질의", hits, client=client, top_k=8)
    assert res.reranked is True
    assert res.fallback_reason is None
    assert [h.chunk_id for h in res.hits] == [2, 1, 0]  # 역순 재정렬


@pytest.mark.parametrize(
    ("exc", "expected_reason"),
    [
        (httpx.ConnectError("연결 실패"), "connect_error"),
        (httpx.TimeoutException("타임아웃"), "timeout"),
        (
            httpx.HTTPStatusError(
                "500",
                request=httpx.Request("POST", "http://litellm/v1/chat/completions"),
                response=httpx.Response(
                    500, request=httpx.Request("POST", "http://litellm/v1/chat/completions")
                ),
            ),
            "http_status_error",
        ),
    ],
)
async def test_rerank_httpx_error_falls_back_bm25(exc, expected_reason):
    hits = [_hit(0, score=3.0), _hit(1, score=2.0)]
    res = await rerank("질의", hits, client=RaisingClient(exc), top_k=8)
    assert res.reranked is False
    assert res.fallback_reason == expected_reason
    assert [h.chunk_id for h in res.hits] == [0, 1]  # BM25 입력 순서 유지(drop 없음)


async def test_rerank_parse_error_falls_back():
    hits = [_hit(0), _hit(1)]
    res = await rerank("질의", hits, client=BadOrderClient(), top_k=8)
    assert res.reranked is False
    assert res.fallback_reason == "parse_error"
    assert len(res.hits) == 2


async def test_rerank_empty_hits():
    res = await rerank("질의", [], client=FakeClient())
    assert res.hits == []
    assert res.reranked is False


async def test_rerank_forces_redaction_before_client():
    """client 입력 후보에 원본 PII 가 없어야 함(레닥션 강제) — 기본 redactor 사용."""
    pii_body = "담당자 hong@cudo.co.kr 주민번호 900101-1234567"
    hits = [_hit(0, body=pii_body)]
    client = FakeClient()
    await rerank("질의", hits, client=client)  # redactor=None → 기본 redaction.redact
    assert client.received is not None
    assert "hong@cudo.co.kr" not in client.received[0]
    assert "900101-1234567" not in client.received[0]
    assert "[이메일]" in client.received[0]


async def test_rerank_redactor_spy_called():
    calls: list[str] = []

    def spy(text: str) -> str:
        calls.append(text)
        return text

    hits = [_hit(0, body="본문A"), _hit(1, body="본문B")]
    await rerank("질의", hits, client=FakeClient(), redactor=spy)
    assert calls == ["본문A", "본문B"]  # 모든 후보 본문이 redactor 통과
