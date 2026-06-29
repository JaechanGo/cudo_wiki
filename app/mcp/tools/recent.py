"""list_recent_posts — 게시판 최신 글 시간순 목록 (검색 아닌 '최근 목록' 요청용).

'최신 공지 보여줘'처럼 키워드 검색이 아니라 게시일 순서가 의도인 질의는 search_regulations(렉시컬)
로는 옛 잡글이 raw 점수로 상위에 와 부적합하다. 이 도구는 ACL 허용 보드의 글을 posted_at 내림차순
으로 그대로 반환한다(LLM 미관여 결정론). board 인자로 게시판명(예 '공지사항') 부분일치 필터.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP
from psycopg.rows import dict_row

from app.common.config import absolute_bizbox_url
from app.common.db import get_pool
from app.mcp.context import Identity, resolve_identity
from app.mcp.schemas import RecentPostItem, RecentPostsOut
from app.mcp.tools._guard import ABSENT_MESSAGE_KO, gate_boards


async def impl_list_recent_posts(
    conn,
    identity: Identity,
    *,
    board: str | None,
    limit: int,
) -> RecentPostsOut:
    """허용 보드의 최신 글을 게시일 내림차순으로 반환. 신원부재면 빈 + 안내."""
    grant = await gate_boards(
        conn, identity, tool_name="list_recent_posts", requested=None
    )
    if grant is None:
        return RecentPostsOut(message_ko=ABSENT_MESSAGE_KO)
    if not grant.allowed_boards:
        return RecentPostsOut(posts=[])

    limit = max(1, min(limit, 30))
    sql = (
        "SELECT p.post_id, p.title, p.posted_at, p.source_url, b.name AS board_name "
        "FROM post p JOIN board b ON b.board_id = p.board_id "
        "WHERE p.board_id = ANY(%(allowed)s) AND b.included "
    )
    params: dict = {"allowed": grant.allowed_boards, "limit": limit}
    if board:
        sql += "AND b.name ILIKE %(board)s "
        params["board"] = f"%{board}%"
    sql += "ORDER BY p.posted_at DESC NULLS LAST, p.post_id DESC LIMIT %(limit)s"

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    posts = [
        RecentPostItem(
            post_id=row["post_id"],
            title=row["title"],
            board_name=row["board_name"],
            posted_at=row["posted_at"].date() if row["posted_at"] else None,
            source_url=absolute_bizbox_url(row["source_url"]),
        )
        for row in rows
    ]
    return RecentPostsOut(posts=posts)


def register_list_recent_posts(mcp: FastMCP) -> None:
    """list_recent_posts 도구 등록."""

    @mcp.tool()
    async def list_recent_posts(
        ctx: Context,
        board: str | None = None,
        limit: int = 10,
    ) -> RecentPostsOut:
        """게시판의 최신 글을 게시일 내림차순(시간순)으로 반환한다. '최신/최근 공지(글) 보여줘'처럼 키워드가 아니라 '최근 목록'을 원하는 요청에 사용한다(이런 질의에 search_regulations 를 쓰면 옛 글이 섞여 나온다). board 로 게시판명(예 '공지사항') 부분일치 필터, limit 기본 10."""
        identity = resolve_identity(ctx)
        async with get_pool().connection() as conn:
            return await impl_list_recent_posts(
                conn, identity, board=board, limit=limit
            )
