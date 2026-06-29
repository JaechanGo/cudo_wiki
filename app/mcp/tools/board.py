"""list_boards — 허용 보드 카탈로그 (Task009 plan §3.4).

ACL 이 곧 결과: included AND board_id ∈ allowed 만 반환. 신원부재는 빈 목록 + audit(fail-closed,
공개 카탈로그 노출 안 함).
"""

from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP
from psycopg.rows import dict_row

from app.common.db import get_pool
from app.mcp.context import Identity, resolve_identity
from app.mcp.schemas import BoardOut, ListBoardsOut
from app.mcp.tools._guard import ABSENT_MESSAGE_KO, gate_boards


async def impl_list_boards(
    conn,
    identity: Identity,
    *,
    board_class: str | None,
) -> ListBoardsOut:
    """허용 보드 목록(허용집합 ∩ included). 신원부재면 빈 + 안내."""
    grant = await gate_boards(conn, identity, tool_name="list_boards", requested=None)
    if grant is None:
        return ListBoardsOut(message_ko=ABSENT_MESSAGE_KO)

    if not grant.allowed_boards:
        return ListBoardsOut(boards=[])

    sql = (
        "SELECT board_id, name, slug, board_class FROM board "
        "WHERE included AND board_id = ANY(%(allowed)s) "
        "AND board_class <> 'video' "  # 영상 보드는 규정 카탈로그서 제외(recommend_videos 전용).
    )
    params: dict = {"allowed": grant.allowed_boards, "bc": board_class}
    if board_class is not None:
        sql += "AND board_class = %(bc)s "
    sql += "ORDER BY board_id"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    boards = [
        BoardOut(
            board_id=row["board_id"], name=row["name"],
            slug=row["slug"], board_class=row["board_class"],
        )
        for row in rows
    ]
    return ListBoardsOut(boards=boards)


def register_list_boards(mcp: FastMCP) -> None:
    """list_boards 도구 등록."""

    @mcp.tool()
    async def list_boards(
        ctx: Context,
        board_class: str | None = None,
    ) -> ListBoardsOut:
        """접근 가능한 게시판(보드) 목록을 반환한다."""
        identity = resolve_identity(ctx)
        async with get_pool().connection() as conn:
            return await impl_list_boards(conn, identity, board_class=board_class)
