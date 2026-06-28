"""get_regulation_diff — 규정 개정 조항 비교 (Task009 plan §3.7).

입력 우선순위: (from_regulation_id+to_regulation_id) 정밀 또는 regulation_id 단건(→ supersedes
체인으로 직전판 자동). 비교 단위 = clause canonical_clause_id. 직전판 부재(최초판)는 added-only.
ACL: 두 regulation 의 board_id 모두 allowed. before/after 는 redact_pii.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP
from psycopg.rows import dict_row

from app.common.db import get_pool
from app.mcp import audit
from app.mcp.context import Identity, resolve_identity
from app.mcp.diff import ClauseRow, compute_clause_diff
from app.mcp.redact_ext import redact_pii
from app.mcp.schemas import ClauseChangeOut, ClauseRefOut, DiffOut
from app.mcp.tools._guard import ABSENT_MESSAGE_KO, DENY_MESSAGE_KO, gate_boards

_NOT_FOUND_KO = "비교할 규정을 찾을 수 없습니다."
_NO_INPUT_KO = "regulation_id 또는 (from/to) 규정 id 가 필요합니다."
_INITIAL_KO = "직전 개정본이 없어 전체를 신규로 표기합니다."


async def _reg_row(conn, regulation_id: int) -> dict | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT regulation_id, board_id, supersedes_regulation_id "
            "FROM regulation WHERE regulation_id = %s",
            (regulation_id,),
        )
        return await cur.fetchone()


async def _clause_rows(conn, regulation_id: int) -> list[ClauseRow]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT canonical_clause_id, clause_label, text FROM clause "
            "WHERE regulation_id = %s ORDER BY order_seq",
            (regulation_id,),
        )
        rows = await cur.fetchall()
    return [
        ClauseRow(
            canonical_clause_id=r["canonical_clause_id"],
            clause_label=r["clause_label"],
            text=r["text"],
        )
        for r in rows
    ]


async def impl_get_regulation_diff(
    conn,
    identity: Identity,
    *,
    from_regulation_id: int | None = None,
    to_regulation_id: int | None = None,
    regulation_id: int | None = None,
) -> DiffOut:
    """규정 개정 diff. 단건이면 supersedes 체인으로 직전판 자동 해석(부재→is_initial)."""
    grant = await gate_boards(
        conn, identity, tool_name="get_regulation_diff", requested=None
    )
    if grant is None:
        return DiffOut(message_ko=ABSENT_MESSAGE_KO)

    # 입력 해석 — to_reg + from_reg(optional).
    if from_regulation_id is not None and to_regulation_id is not None:
        to_id = to_regulation_id
        to_row = await _reg_row(conn, to_id)
        from_id = from_regulation_id
    elif regulation_id is not None:
        to_id = regulation_id
        to_row = await _reg_row(conn, to_id)
        from_id = to_row["supersedes_regulation_id"] if to_row else None
    else:
        return DiffOut(message_ko=_NO_INPUT_KO)

    if to_row is None:
        return DiffOut(message_ko=_NOT_FOUND_KO)

    from_row = await _reg_row(conn, from_id) if from_id is not None else None

    # ACL — to/from 모두 허용 보드.
    board_ids = [to_row["board_id"]]
    if from_row is not None:
        board_ids.append(from_row["board_id"])
    denied = [b for b in board_ids if b not in grant.allowed_boards]
    if denied:
        await audit.write_acl_audit(
            conn, tool_name="get_regulation_diff", identity=identity, decision="deny",
            allowed=grant.allowed_boards, denied=denied, reason="board_not_allowed",
        )
        return DiffOut(message_ko=DENY_MESSAGE_KO)

    to_rows = await _clause_rows(conn, to_id)
    is_initial = from_row is None
    from_rows = [] if is_initial else await _clause_rows(conn, from_id)
    diff = compute_clause_diff(from_rows, to_rows)

    return DiffOut(
        from_regulation_id=from_id if not is_initial else None,
        to_regulation_id=to_id,
        is_initial=is_initial,
        added=[ClauseRefOut(canonical_clause_id=r.canonical_clause_id,
                            clause_label=r.clause_label) for r in diff.added],
        removed=[ClauseRefOut(canonical_clause_id=r.canonical_clause_id,
                             clause_label=r.clause_label) for r in diff.removed],
        changed=[ClauseChangeOut(
            canonical_clause_id=c.canonical_clause_id, clause_label=c.clause_label,
            before=redact_pii(c.before), after=redact_pii(c.after),
        ) for c in diff.changed],
        message_ko=_INITIAL_KO if is_initial else None,
    )


def register_get_regulation_diff(mcp: FastMCP) -> None:
    """get_regulation_diff 도구 등록."""

    @mcp.tool()
    async def get_regulation_diff(
        ctx: Context,
        regulation_id: int | None = None,
        from_regulation_id: int | None = None,
        to_regulation_id: int | None = None,
    ) -> DiffOut:
        """규정 개정 전후의 조항 변경(added/removed/changed)을 비교한다."""
        identity = resolve_identity(ctx)
        async with get_pool().connection() as conn:
            return await impl_get_regulation_diff(
                conn, identity, from_regulation_id=from_regulation_id,
                to_regulation_id=to_regulation_id, regulation_id=regulation_id,
            )
