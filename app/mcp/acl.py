"""ACL — 허용 board_ids 해석·필터·신원부재 정책 (Task009 plan §4.3·§4.4).

v1 정책: 신원이 존재(인증 직원)하면 → 포함 보드 전체 허용(역할 게이팅 없음, phase-2). 민감 보드는
board_seed 에서 included=false/DB 부재로 구조적 제외. 신원부재 → 빈(fail-closed). filter 는 순수,
allowed 는 1 DB read.
"""

from __future__ import annotations

from app.mcp.context import Identity


async def allowed_board_ids(conn, identity: Identity) -> list[int]:
    """신원이 있으면 포함 보드 전체, 없으면 빈 리스트(fail-closed, §4.4)."""
    if not identity.raw_present:
        return []
    async with conn.cursor() as cur:
        await cur.execute("SELECT board_id FROM board WHERE included ORDER BY board_id")
        rows = await cur.fetchall()
    return [r[0] for r in rows]


async def video_board_ids(conn) -> list[int]:
    """board_class='video' 보드 id 목록 — 영상 전용 분리 축.

    included 는 all-or-nothing 게이트라 '한 도구에만 노출'을 못 한다. 영상 보드는 included=true 로
    두되(recommend_videos 의 gate 통과 위해), 규정/일반 검색·목록·카탈로그(search_regulations·
    list_recent_posts·list_boards)에서는 이 id 들을 명시적으로 제외해 영상이 새어들지 않게 한다.
    """
    async with conn.cursor() as cur:
        await cur.execute("SELECT board_id FROM board WHERE board_class = 'video'")
        rows = await cur.fetchall()
    return [r[0] for r in rows]


def filter_board_ids(
    requested: list[int] | None, allowed: list[int]
) -> tuple[list[int], list[int]]:
    """요청 보드 ∩ 허용 보드 = (유효, 거부). requested=None 이면 허용 전체.

    유효 리스트는 요청 순서 보존·중복 제거. 거부(allowed 밖)는 별도 추적(민감보드 요청 감사).
    """
    if requested is None:
        return list(allowed), []
    allowed_set = set(allowed)
    effective: list[int] = []
    denied: list[int] = []
    seen: set[int] = set()
    for board_id in requested:
        if board_id in seen:
            continue
        seen.add(board_id)
        if board_id in allowed_set:
            effective.append(board_id)
        else:
            denied.append(board_id)
    return effective, denied
