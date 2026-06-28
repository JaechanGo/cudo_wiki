"""get_approval_authority — 전결권자/금액밴드 (Task009 plan §3.5, M-2).

B aggregate(approver/approval_line 분기) 호출 + condition_note **C 직접 SQL 보강**(M-2: B 가
condition_note 미반환 → canonical_authority_id 로 authority_matrix 직접 조회 후 redact). 질의 로깅.
"""

from __future__ import annotations

import time

from mcp.server.fastmcp import Context, FastMCP
from psycopg.rows import dict_row

from app.common.db import get_pool
from app.mcp import audit
from app.mcp.context import Identity, resolve_identity
from app.mcp.redact_ext import redact_pii
from app.mcp.schemas import AuthorityOut, AuthorityRowOut
from app.mcp.tools._guard import ABSENT_MESSAGE_KO, gate_boards
from app.search import aggregate


async def _condition_notes(conn, canonical_ids: list[str]) -> dict[str, str | None]:
    """M-2: canonical_authority_id 집합으로 condition_note 를 C 직접 SQL 보강 조회."""
    if not canonical_ids:
        return {}
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT canonical_authority_id, condition_note FROM authority_matrix "
            "WHERE canonical_authority_id = ANY(%(ids)s) AND is_current",
            {"ids": canonical_ids},
        )
        rows = await cur.fetchall()
    return {r["canonical_authority_id"]: r["condition_note"] for r in rows}


async def impl_get_approval_authority(
    conn,
    identity: Identity,
    *,
    query: str,
    amount: int | None,
    board_ids: list[int] | None,
) -> AuthorityOut:
    """전결 집계 + condition_note 보강·레닥션. 0행이면 count=0(거절 게이트 비적용)."""
    started = time.monotonic()
    grant = await gate_boards(
        conn, identity, tool_name="get_approval_authority", requested=board_ids
    )
    if grant is None:
        return AuthorityOut(kind="", count=0, message_ko=ABSENT_MESSAGE_KO)

    # amount 명시 입력은 질의에 "{amount}원" 합성(B 금액 파싱 신뢰).
    agg_query = f"{query} {amount}원" if amount is not None else query
    # ACL: 허용/유효 보드 명시 리스트를 그대로 전달(빈 리스트면 fail-closed 0행). None 전달 금지
    # — 요청 보드가 전부 거부돼 eff=[] 일 때 None 으로 바뀌면 전체 보드 조회(ACL 우회)가 됨.
    agg = await aggregate(conn, agg_query, board_ids=grant.effective_boards)

    canonical_ids = [
        r.extra["canonical_authority_id"]
        for r in agg.rows
        if r.extra.get("canonical_authority_id")
    ]
    notes = await _condition_notes(conn, canonical_ids)

    rows_out: list[AuthorityRowOut] = []
    for row in agg.rows:
        cid = row.extra.get("canonical_authority_id")
        note = notes.get(cid) if cid else None
        rows_out.append(
            AuthorityRowOut(
                business_item=row.label,
                approver_role=row.value if isinstance(row.value, str) else None,
                action_type=row.extra.get("action_type"),
                consulter_roles=row.extra.get("consulter_roles"),
                amount_min=row.extra.get("amount_min"),
                amount_max=row.extra.get("amount_max"),
                condition_note=redact_pii(note) if note else None,
                citation=cid,
            )
        )

    await audit.write_query_log(
        conn, query_text=query, normalized=agg_query, identity=identity,
        result_count=agg.count, zero_result=agg.count == 0, abstained=False,
        validator_passed=None, strategy=agg.kind, reranked=False,
        returned_canonical_ids=canonical_ids, answer_citation_ids=canonical_ids,
        top_score=None, latency_ms=int((time.monotonic() - started) * 1000),
    )

    message = None if agg.count else "해당 전결규정을 찾지 못했습니다."
    return AuthorityOut(kind=agg.kind, count=agg.count, rows=rows_out, message_ko=message)


def register_get_approval_authority(mcp: FastMCP) -> None:
    """get_approval_authority 도구 등록."""

    @mcp.tool()
    async def get_approval_authority(
        query: str,
        ctx: Context,
        amount: int | None = None,
        board_ids: list[int] | None = None,
    ) -> AuthorityOut:
        """업무항목/금액의 전결권자·결재라인을 결정론 인용과 함께 반환한다."""
        identity = resolve_identity(ctx)
        async with get_pool().connection() as conn:
            return await impl_get_approval_authority(
                conn, identity, query=query, amount=amount, board_ids=board_ids
            )
