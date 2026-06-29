"""recommend_videos — 지식뱅크(gainge) 영상 추천 (영상 board 전용 검색).

'OOO 관련 영상 추천'처럼 사내 동영상/강의를 원하는 요청에 쓴다. 규정/공지 검색(search_regulations)
과 분리: 영상 board(board_class='video')만 검색해 항상 top-N 을 돌려준다(추천이므로 decide_abstain
생략 — 점수 낮아도 가장 관련된 영상을 제시). 출력은 제목·카테고리(board)·재생링크(video_url=source_url).
"""

from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from app.common.db import get_pool
from app.mcp.acl import video_board_ids
from app.mcp.context import Identity, resolve_identity
from app.mcp.redact_ext import redact_pii
from app.mcp.schemas import VideoItem, VideoRecOut
from app.mcp.sources import build_source
from app.mcp.tools._guard import ABSENT_MESSAGE_KO, gate_boards
from app.search import rerank, search

_NO_VIDEO_KO = "등록된 사내 영상이 없습니다."


async def impl_recommend_videos(
    conn,
    identity: Identity,
    *,
    query: str,
    limit: int,
) -> VideoRecOut:
    """영상 board 만 검색→리랭크→top-N. 신원부재 fail-closed, abstain 없음(항상 추천)."""
    video_ids = await video_board_ids(conn)
    if not video_ids:
        return VideoRecOut(message_ko=_NO_VIDEO_KO)

    grant = await gate_boards(
        conn, identity, tool_name="recommend_videos", requested=video_ids
    )
    if grant is None:
        return VideoRecOut(message_ko=ABSENT_MESSAGE_KO)
    if not grant.effective_boards:
        return VideoRecOut(videos=[])

    limit = max(1, min(limit, 20))
    # 리랭크 후보를 넉넉히(>=8) 받아 의미 재정렬 후 limit 으로 자른다. only_current=False:
    # 영상은 is_current 개정 개념이 약해 전부 후보.
    sr = await search(
        conn, query, board_ids=grant.effective_boards,
        only_current=False, limit=max(limit, 8),
    )
    rr = await rerank(query, sr.hits, client=None)
    final = (rr.hits if rr.hits else sr.hits)[:limit]

    videos: list[VideoItem] = []
    for hit in final:
        src = await build_source(conn, hit=hit)
        videos.append(
            VideoItem(
                title=src.title or "",
                board_name=src.board_name,
                video_url=src.source_url,
                snippet=(redact_pii(hit.body)[:300] if hit.body else None),
                score=hit.score,
                posted_at=hit.posted_at.date() if hit.posted_at else None,
            )
        )
    return VideoRecOut(videos=videos)


def register_recommend_videos(mcp: FastMCP) -> None:
    """recommend_videos 도구 등록."""

    @mcp.tool()
    async def recommend_videos(
        query: str,
        ctx: Context,
        limit: int = 5,
    ) -> VideoRecOut:
        """사내 지식뱅크 영상(교육·강의·홍보 동영상)을 질의 관련도순으로 추천한다. 'OOO 관련 영상 추천해줘', '동영상/강의 찾아줘'처럼 영상을 원하는 요청에 사용한다(규정·문서 검색은 search_regulations). 각 영상의 video_url(재생 링크)을 [제목](video_url) 마크다운 링크로 제시하라."""
        identity = resolve_identity(ctx)
        async with get_pool().connection() as conn:
            return await impl_recommend_videos(
                conn, identity, query=query, limit=limit
            )
