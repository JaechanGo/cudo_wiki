"""get_regulation — 규정 본문 + 조항 목록 (Task009 plan §3.2).

직접 SQL(regulation + clause). ACL: regulation.board_id ∈ allowed. 조항 text 는 redact_pii. 미존재/
비허용은 message_ko 안내(에러 아님).
"""

from __future__ import annotations

from datetime import date

from mcp.server.fastmcp import Context, FastMCP
from psycopg.rows import dict_row

from app.common.db import get_pool
from app.mcp import audit
from app.mcp.context import Identity, resolve_identity
from app.mcp.redact_ext import redact_pii
from app.mcp.schemas import ClauseOut, RegulationOut
from app.mcp.sources import build_source
from app.mcp.tools._guard import ABSENT_MESSAGE_KO, DENY_MESSAGE_KO, gate_boards

_NOT_FOUND_KO = "해당 규정을 찾을 수 없습니다."


async def impl_get_regulation(
    conn,
    identity: Identity,
    *,
    regulation_id: int,
    as_of: date | None,
) -> RegulationOut:
    """규정 1건 + 현행 조항(order_seq 순)을 레닥션해 반환한다."""
    grant = await gate_boards(
        conn, identity, tool_name="get_regulation", requested=None
    )
    if grant is None:
        return RegulationOut(message_ko=ABSENT_MESSAGE_KO)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT regulation_id, board_id, title, reg_type, effective_date, revision_no "
            "FROM regulation WHERE regulation_id = %s",
            (regulation_id,),
        )
        reg = await cur.fetchone()

    if reg is None:
        return RegulationOut(message_ko=_NOT_FOUND_KO)

    if reg["board_id"] not in grant.allowed_boards:
        await audit.write_acl_audit(
            conn, tool_name="get_regulation", identity=identity, decision="deny",
            allowed=grant.allowed_boards, denied=[reg["board_id"]],
            reason="board_not_allowed",
        )
        return RegulationOut(message_ko=DENY_MESSAGE_KO)

    # 현행 조항(as_of 주면 시행일 이전 버전까지). v1 은 is_current 우선.
    sql = (
        "SELECT canonical_clause_id, clause_label, clause_title, text "
        "FROM clause WHERE regulation_id = %(rid)s AND is_current "
    )
    params: dict = {"rid": regulation_id, "as_of": as_of}
    if as_of is not None:
        sql += "AND (effective_date IS NULL OR effective_date <= %(as_of)s) "
    sql += "ORDER BY order_seq"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        clause_rows = await cur.fetchall()

    clauses = [
        ClauseOut(
            canonical_clause_id=row["canonical_clause_id"],
            clause_label=row["clause_label"],
            clause_title=row["clause_title"],
            text=redact_pii(row["text"]),
        )
        for row in clause_rows
    ]
    source = await build_source(conn, regulation_id=regulation_id)
    return RegulationOut(
        regulation_id=reg["regulation_id"],
        title=reg["title"],
        reg_type=reg["reg_type"],
        effective_date=reg["effective_date"],
        revision_no=reg["revision_no"],
        source=source,
        clauses=clauses,
    )


def register_get_regulation(mcp: FastMCP) -> None:
    """get_regulation 도구 등록."""

    @mcp.tool()
    async def get_regulation(
        regulation_id: int,
        ctx: Context,
        as_of: date | None = None,
    ) -> RegulationOut:
        """규정 1건의 본문(조항 목록)을 결정론 출처와 함께 반환한다."""
        identity = resolve_identity(ctx)
        async with get_pool().connection() as conn:
            return await impl_get_regulation(
                conn, identity, regulation_id=regulation_id, as_of=as_of
            )
