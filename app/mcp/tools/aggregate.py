"""aggregate_compare — 보드별 현행 규정 카운트 비교 (Task009 plan §3.6, m-4).

v1 = 보드별 현행 규정 카운트 비교 한정(차집합·추세 등 미지원). B aggregate 의 board_count 분기를
사용하되, label(=board_id 문자열)을 보드명으로 치환. AGGREGATE intent 보장을 위해 비-AGGREGATE
질의면 키워드를 합성한다.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP
from psycopg.rows import dict_row

from app.common.db import get_pool
from app.mcp.context import Identity, resolve_identity
from app.mcp.schemas import CompareOut, CompareRowOut
from app.mcp.tools._guard import ABSENT_MESSAGE_KO, gate_boards
from app.search import aggregate, classify_intent
from app.search.types import QueryIntent


async def _board_names(conn, board_ids: list[int]) -> dict[int, str]:
    if not board_ids:
        return {}
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT board_id, name FROM board WHERE board_id = ANY(%(ids)s)",
            {"ids": board_ids},
        )
        rows = await cur.fetchall()
    return {r["board_id"]: r["name"] for r in rows}


async def impl_aggregate_compare(
    conn,
    identity: Identity,
    *,
    query: str,
    board_ids: list[int] | None,
) -> CompareOut:
    """보드별 현행 규정 카운트 비교(v1 카운트 한정). label 을 board_id→보드명 치환."""
    grant = await gate_boards(
        conn, identity, tool_name="aggregate_compare", requested=board_ids
    )
    if grant is None:
        return CompareOut(kind="", count=0, message_ko=ABSENT_MESSAGE_KO)

    # board_count 분기 보장 — AGGREGATE 미분류면 키워드 합성(v1 카운트 비교 한정).
    agg_query = query if classify_intent(query) == QueryIntent.AGGREGATE else f"{query} 비교"
    # ACL: 명시 보드 리스트 그대로 전달(eff=[] 면 fail-closed 0행). None 으로 바꾸면 ACL 우회.
    agg = await aggregate(conn, agg_query, board_ids=grant.effective_boards)

    # board_count 행 label = str(board_id) → 보드명 치환.
    row_board_ids = [int(r.label) for r in agg.rows if r.label.isdigit()]
    names = await _board_names(conn, row_board_ids)
    rows_out = [
        CompareRowOut(
            board_id=int(r.label),
            label=names.get(int(r.label), r.label),
            value=r.value if isinstance(r.value, int) else None,
        )
        for r in agg.rows
        if r.label.isdigit()
    ]
    message = None if rows_out else "비교할 보드별 규정 카운트가 없습니다."
    return CompareOut(kind=agg.kind, count=len(rows_out), rows=rows_out, message_ko=message)


def register_aggregate_compare(mcp: FastMCP) -> None:
    """aggregate_compare 도구 등록."""

    @mcp.tool()
    async def aggregate_compare(
        query: str,
        ctx: Context,
        board_ids: list[int] | None = None,
    ) -> CompareOut:
        """보드별 현행 규정 건수를 비교한다 (v1=카운트 비교 한정; 차집합·추세 미지원)."""
        identity = resolve_identity(ctx)
        async with get_pool().connection() as conn:
            return await impl_aggregate_compare(
                conn, identity, query=query, board_ids=board_ids
            )
