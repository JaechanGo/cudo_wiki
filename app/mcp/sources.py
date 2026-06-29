"""결정론 출처메타 조립 (Task009 plan §6).

LLM 미관여 단일 빌더 — 모든 도구가 동일 구조(SourceMeta)를 생성한다. 조번호/시행일은 메타에서만
(생성 금지). 결정론: 동일 입력 → 동일 출력, 첨부는 attachment_id 오름차순 고정 정렬.

``assemble_source_meta`` 는 순수(행 주입), ``build_source`` 는 DB 조회(JOIN) 후 조립 위임.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from psycopg.rows import dict_row

from app.common.config import absolute_bizbox_url
from app.mcp.schemas import AttachmentRef, SourceMeta
from app.search.types import SearchHit


def assemble_source_meta(
    *,
    board_id: int,
    board_name: str,
    post_id: int | None,
    title: str,
    reg_code: str | None,
    effective_date: date | None,
    source_url: str | None,
    attachment_rows: Sequence[Mapping],
) -> SourceMeta:
    """행 데이터 → SourceMeta(순수). 첨부는 attachment_id 오름차순 정렬(결정론)."""
    attachments = [
        AttachmentRef(
            attachment_id=row["attachment_id"],
            file_name=row["file_name"],
            kind=row["kind"],
            download_url=absolute_bizbox_url(row.get("download_url")),
        )
        for row in sorted(attachment_rows, key=lambda r: r["attachment_id"])
    ]
    return SourceMeta(
        board_id=board_id,
        board_name=board_name,
        post_id=post_id,
        title=title,
        reg_code=reg_code,
        effective_date=effective_date,
        source_url=source_url,
        attachments=attachments,
    )


async def _resolve_post_and_reg(
    conn, *, hit: SearchHit | None, regulation_id: int | None, post_id: int | None
) -> tuple[int | None, int | None]:
    """hit/regulation_id/post_id 중 주어진 것으로 (post_id, regulation_id) 를 해석한다."""
    if hit is not None:
        if hit.source_post_id is not None:
            return hit.source_post_id, None
        if hit.clause_id is not None:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT regulation_id FROM clause WHERE clause_id = %s", (hit.clause_id,)
                )
                row = await cur.fetchone()
            regulation_id = row[0] if row else None
        elif hit.authority_id is not None:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT regulation_id FROM authority_matrix WHERE authority_id = %s",
                    (hit.authority_id,),
                )
                row = await cur.fetchone()
            regulation_id = row[0] if row else None
    if post_id is None and regulation_id is not None:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT source_post_id FROM regulation WHERE regulation_id = %s",
                (regulation_id,),
            )
            row = await cur.fetchone()
        post_id = row[0] if row else None
    return post_id, regulation_id


async def build_source(
    conn,
    *,
    hit: SearchHit | None = None,
    regulation_id: int | None = None,
    post_id: int | None = None,
) -> SourceMeta:
    """hit/regulation_id/post_id 중 하나로 출처메타를 조립한다(JOIN → assemble 위임)."""
    board_id = hit.board_id if hit is not None else None
    resolved_post, resolved_reg = await _resolve_post_and_reg(
        conn, hit=hit, regulation_id=regulation_id, post_id=post_id
    )

    title = ""
    source_url = None
    reg_code = None
    effective_date = None

    async with conn.cursor(row_factory=dict_row) as cur:
        # 규정 메타(reg_code·effective_date·title·board) — regulation 기점.
        if resolved_reg is not None:
            await cur.execute(
                "SELECT board_id, reg_code, effective_date, title, source_post_id "
                "FROM regulation WHERE regulation_id = %s",
                (resolved_reg,),
            )
            reg = await cur.fetchone()
            if reg is not None:
                board_id = board_id or reg["board_id"]
                reg_code = reg["reg_code"]
                effective_date = reg["effective_date"]
                title = reg["title"]
                resolved_post = resolved_post or reg["source_post_id"]

        # 글 메타(title·source_url·board) — post 기점(규정 title 보다 우선하지 않게 빈 경우만).
        if resolved_post is not None:
            await cur.execute(
                "SELECT board_id, title, source_url FROM post WHERE post_id = %s",
                (resolved_post,),
            )
            post = await cur.fetchone()
            if post is not None:
                board_id = board_id or post["board_id"]
                if not title:
                    title = post["title"]
                source_url = post["source_url"]

        # board 이름.
        board_name = ""
        if board_id is not None:
            await cur.execute("SELECT name FROM board WHERE board_id = %s", (board_id,))
            brow = await cur.fetchone()
            board_name = brow["name"] if brow else ""

        # 첨부 링크(post 기준).
        attachment_rows: list[Mapping] = []
        if resolved_post is not None:
            await cur.execute(
                "SELECT attachment_id, file_name, kind, download_url FROM attachment "
                "WHERE post_id = %s ORDER BY attachment_id",
                (resolved_post,),
            )
            attachment_rows = await cur.fetchall()

    return assemble_source_meta(
        board_id=board_id or 0,
        board_name=board_name,
        post_id=resolved_post,
        title=title,
        reg_code=reg_code,
        effective_date=effective_date,
        source_url=source_url,
        attachment_rows=attachment_rows,
    )
