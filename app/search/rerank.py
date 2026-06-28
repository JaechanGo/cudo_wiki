"""GLM 리랭크 + PII 레닥션 강제 + BM25 폴백 (plan §5).

★ NOGO 제약: 비레닥션 본문을 GLM 에 전송 금지 → 후보는 반드시 redactor 를 통과한 본문만 client 에
전달. 모든 GLM 오류류(httpx.HTTPError 상위·타임아웃·연결·non-200·파싱)는 catch 해 BM25-only 폴백
(hit drop 없음 — NFR 검색 동작 보장, D-09).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from app.common.logging import get_logger
from app.search import redaction
from app.search.glm_client import GlmClient, RerankClient
from app.search.types import RerankResult, SearchHit

_logger = get_logger("app.search.rerank")


def _fallback_reason(exc: httpx.HTTPError) -> str:
    """httpx 오류 종류 → 폴백 사유 코드."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect_error"
    if isinstance(exc, httpx.HTTPStatusError):
        return "http_status_error"
    return "http_error"


def _reorder(hits: list[SearchHit], order: list[int]) -> list[SearchHit]:
    """순위 인덱스대로 재정렬하고, 누락된 hit 은 원순서로 뒤에 append(절대 drop 안 함)."""
    seen: set[int] = set()
    ordered: list[SearchHit] = []
    for idx in order:
        if idx not in seen:
            seen.add(idx)
            ordered.append(hits[idx])
    for i, hit in enumerate(hits):
        if i not in seen:
            ordered.append(hit)
    return ordered


async def rerank(
    query: str,
    hits: list[SearchHit],
    *,
    client: RerankClient | None = None,
    top_k: int = 8,
    redactor: Callable[[str], str] | None = None,
    timeout_s: float = 8.0,
) -> RerankResult:
    """GLM 으로 hits 를 top_k 로 재정렬한다. 미도달/파싱오류 시 BM25-only 폴백.

    redactor: test-only override; 운영 경로(route)는 이 인자를 노출하지 않고 내부 기본값
    (redaction.redact)으로만 호출한다 → 운영에서 비레닥션 본문의 GLM 전송은 우회 불가(minor-1).
    """
    if not hits:
        return RerankResult(hits=[], reranked=False, fallback_reason=None)

    redact = redactor or redaction.redact
    candidates = [redact(h.body) for h in hits]

    if client is None:
        client = GlmClient(timeout_s=timeout_s)

    try:
        order = await client.rank(query, candidates)
    except httpx.HTTPError as exc:
        reason = _fallback_reason(exc)
        _logger.warning("GLM 리랭크 실패(%s) → BM25 폴백: %s", reason, exc)
        return RerankResult(hits=hits[:top_k], reranked=False, fallback_reason=reason)
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        _logger.warning("GLM 리랭크 응답 파싱 실패 → BM25 폴백: %s", exc)
        return RerankResult(hits=hits[:top_k], reranked=False, fallback_reason="parse_error")

    if not isinstance(order, list) or any(
        not isinstance(i, int) or i < 0 or i >= len(hits) for i in order
    ):
        _logger.warning("GLM 리랭크 인덱스 범위 오류 → BM25 폴백: %r", order)
        return RerankResult(hits=hits[:top_k], reranked=False, fallback_reason="parse_error")

    reordered = _reorder(hits, order)
    return RerankResult(hits=reordered[:top_k], reranked=True, fallback_reason=None)
