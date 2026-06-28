"""감사/로깅 — email 해시(PIPA) + query_log / acl_audit 쓰기 (Task009 §5.3·§7.3).

★ email 원문 저장 금지(PIPA): 항상 ``hash_email`` 해시로만 적재. role 은 원문 OK(PII 아님).
쓰기 경계(m-3): query_log/acl_audit 쓰기는 읽기 도구와 분리된 짧은 트랜잭션 + 명시 commit.
감사 쓰기 실패가 도구 본기능을 막지 않도록 best-effort(실패 시 구조화 로그로 강등).
(DB 쓰기 함수는 도구 결선 단계에서 추가 — 본 모듈은 우선 해시 유틸 제공.)
"""

from __future__ import annotations

import hashlib

from app.common.logging import get_logger
from app.mcp.context import Identity

_logger = get_logger("app.mcp.audit")


def hash_email(email: str | None) -> str | None:
    """``sha256(email.strip().lower())`` 16진 해시. 빈값/None 은 None(원문 저장 금지)."""
    if email is None:
        return None
    normalized = email.strip().lower()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode()).hexdigest()


async def write_acl_audit(
    conn,
    *,
    tool_name: str,
    identity: Identity,
    decision: str,
    requested: list[int] | None = None,
    allowed: list[int] | None = None,
    denied: list[int] | None = None,
    reason: str | None = None,
) -> None:
    """보안 이벤트(deny/identity_absent/filtered)를 acl_audit 에 적재(§5.2).

    m-3: ``conn.transaction()`` 블록으로 명시 commit 경계. best-effort — 실패 시 savepoint 롤백 +
    경고 로그(본기능 비차단, 트랜잭션 abort 방지). email 원문 금지(해시).
    """
    try:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO acl_audit (tool_name, user_role, user_email_hash, "
                "identity_present, decision, requested_board_ids, allowed_board_ids, "
                "denied_board_ids, reason, session_id) "
                "VALUES (%(tool)s, %(role)s, %(email_hash)s, %(present)s, %(decision)s, "
                "%(requested)s, %(allowed)s, %(denied)s, %(reason)s, %(session)s)",
                {
                    "tool": tool_name,
                    "role": identity.role,
                    "email_hash": hash_email(identity.email),
                    "present": identity.raw_present,
                    "decision": decision,
                    "requested": requested,
                    "allowed": allowed,
                    "denied": denied,
                    "reason": reason,
                    "session": identity.session_id,
                },
            )
    except Exception as exc:  # best-effort — 보안 이벤트 쓰기 실패는 WARNING 가시화(§7.3).
        _logger.warning(
            "acl_audit 쓰기 실패(best-effort) tool=%s decision=%s: %s",
            tool_name, decision, exc,
        )


async def write_query_log(
    conn,
    *,
    query_text: str,
    normalized: str | None,
    identity: Identity,
    result_count: int,
    zero_result: bool,
    abstained: bool,
    validator_passed: bool | None,
    strategy: str | None,
    reranked: bool,
    returned_canonical_ids: list[str] | None,
    answer_citation_ids: list[str] | None,
    top_score: float | None,
    latency_ms: int | None,
) -> None:
    """검색/집계 질의 1건을 query_log 에 적재(§5.3, 평가 하네스 입력). best-effort + 명시 경계."""
    try:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO query_log (query_text, normalized_query, user_role, "
                "user_email_hash, result_count, zero_result, abstained, validator_passed, "
                "retrieval_strategy, reranked, returned_canonical_ids, answer_citation_ids, "
                "top_score, latency_ms, session_id) "
                "VALUES (%(q)s, %(nq)s, %(role)s, %(email_hash)s, %(rc)s, %(zr)s, %(ab)s, "
                "%(vp)s, %(strat)s, %(rr)s, %(rcid)s, %(acid)s, %(ts)s, %(lat)s, %(session)s)",
                {
                    "q": query_text,
                    "nq": normalized,
                    "role": identity.role,
                    "email_hash": hash_email(identity.email),
                    "rc": result_count,
                    "zr": zero_result,
                    "ab": abstained,
                    "vp": validator_passed,
                    "strat": strategy,
                    "rr": reranked,
                    "rcid": returned_canonical_ids,
                    "acid": answer_citation_ids,
                    "ts": top_score,
                    "lat": latency_ms,
                    "session": identity.session_id,
                },
            )
    except Exception as exc:  # best-effort — 질의 로깅 실패가 검색 응답을 막지 않음.
        _logger.warning("query_log 쓰기 실패(best-effort): %s", exc)
