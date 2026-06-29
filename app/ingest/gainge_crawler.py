"""gainge 지식뱅크 영상 크롤 — crawler.py 와 동일 시그니처(list_post_refs/crawl_post)의 GraphQL판.

단일 'gainge 영상' 보드(board_no=800000000)로 **전 카테고리**를 수집한다(board_no 는 무시).
흐름: Get_all_category_groups → 카테고리 seq 전체 → 카테고리별 Posts(페이지 순회) → 게시글 dict.
게시글 메타/본문(description+content HTML)+영상링크를 body_html 로 합본해 RawPost 로 반환한다.
첨부는 없으므로(attachments=()) run 의 다운로드·추출 경로를 타지 않는다(영상은 /post/{seq} 링크).

워터마크: gainge post seq 는 전역 증가키 → since_art_no 이하 seq 는 skip(이미 수집분). 단 카테고리별
seq 가 비단조라 조기종료(break)는 하지 않고 전 카테고리를 순회한 뒤 seq 로 dedup(upsert 멱등 보강).
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.ingest.models import PostRef, RawPost

if TYPE_CHECKING:
    from app.ingest.gainge_client import GaingeClient

_MAX_PAGES = 200  # 카테고리당 페이지 안전캡.

# 카테고리 그룹·카테고리 seq 트리.
_CATEGORY_QUERY = (
    "query Get_all_category_groups($input: GetAllCategoryGroupsInput) {"
    " get_all_category_groups(input: $input) { categoryGroups {"
    " name categories { seq name visibility_status is_using } } } }"
)
# 게시글 목록 — 영상 메타/본문/클립을 한 번에(상세 재조회 불요).
_POSTS_QUERY = (
    "query Posts($input: GetAllPostsInput!) {"
    " get_all_posts(input: $input) { posts {"
    " totalCount totalPages currentPage postsByUser {"
    " seq title description content uploader published_at created_at"
    " view_cnt is_video running_time_text postCategoryGroupName postCategoryName"
    " clip { register_value ott_hls_path } } } } }"
)


def _parse_published(value: object) -> datetime | None:
    """ISO8601(예 '2024-03-05T06:38:08.000Z') → aware datetime(UTC). 비문자열/파싱실패 시 None.

    GraphQL dict[str, Any] 값이라 런타임 타입 보장이 없다(epoch int 등 가능). isinstance 가드로
    비문자열을 None 격하 — list_post_refs 는 per-post try 밖이라 여기서 예외가 나면 보드 전체 크롤이
    중단된다(글 단위 실패격리 우회). docstring 계약('실패 시 None')을 타입오류까지 지키게 한다.
    """
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _all_category_seqs(client: GaingeClient) -> list[int]:
    """전 카테고리 그룹에서 사용중(is_using) 카테고리 seq 목록(중복 제거, 출현순)."""
    data = client.graphql(
        "Get_all_category_groups", _CATEGORY_QUERY, {"input": {"ignoreVisible": True}}
    )
    groups = (data.get("get_all_category_groups") or {}).get("categoryGroups") or []
    seqs: list[int] = []
    seen: set[int] = set()
    for grp in groups:
        for cat in grp.get("categories") or []:
            seq = cat.get("seq")
            if seq is None or seq in seen or cat.get("is_using") is False:
                continue
            seen.add(seq)
            seqs.append(seq)
    return seqs


def _posts_in_category(
    client: GaingeClient, category_seq: int, per_page: int
) -> list[dict[str, Any]]:
    """카테고리 1개의 전 게시글 dict(페이지 순회). 권한없음(FORBIDDEN) 등 카테고리 단위 오류는 격리.

    일부 카테고리(visibility 제한)는 Posts 조회가 403 'FORBIDDEN'(GraphQL errors → RuntimeError)을
    던진다. list_post_refs 는 crawl_board 의 per-post try 밖에서 실행되므로, 여기서 카테고리 단위로
    격리하지 않으면 한 카테고리의 403 이 보드 전체 크롤을 중단시킨다(접근 가능한 나머지도 못 받음).
    네트워크/HTTP 오류(httpx)는 격리하지 않고 전파해 전체 재시도에 맡긴다.
    """
    out: list[dict[str, Any]] = []
    page = 1
    while page <= _MAX_PAGES:
        try:
            data = client.graphql(
                "Posts", _POSTS_QUERY,
                {"input": {"limit": per_page, "categorySeq": category_seq, "order": 2, "page": page}},
            )
        except RuntimeError as exc:
            print(f"[gainge] 카테고리 {category_seq} 건너뜀(접근불가/오류): {exc}", file=sys.stderr)
            break
        posts = (data.get("get_all_posts") or {}).get("posts") or {}
        items = posts.get("postsByUser") or []
        out.extend(items)
        total_pages = posts.get("totalPages") or 1
        if not items or page >= total_pages:
            break
        page += 1
    return out


def list_post_refs(
    client: GaingeClient,
    board_no: int,  # 800000000 sentinel(단일 gainge 보드) — 미사용.
    since_art_no: int | None,  # gainge 는 워터마크 미사용 — 호환 위해 받기만 한다.
    since_posted_at: datetime | None,
    *,
    per_page: int = 50,
) -> list[PostRef]:
    """전 카테고리 게시글 → PostRef(seq=art_no) **전량**. client._cache 에 게시글 dict 동시 적재.

    ★ gainge 는 매 실행 전체 수집한다(seq 워터마크 증분 안 함). 카테고리별 seq 가 비단조라 seq
    워터마크로 필터하면, 낮은 seq 글이 한 번 처리 실패(일시적 오류)하고 같은 run 의 높은 seq 글이
    성공할 때 워터마크(GREATEST)가 점프해 실패 글이 영구 누락된다(cross-run loss). 데이터가
    가벼우므로(수백 건) 전량 수집 + upsert 멱등(content_hash 동일 시 no-op)으로 누락을 원천 차단한다.
    """
    out: list[PostRef] = []
    seen: set[int] = set()
    for category_seq in _all_category_seqs(client):
        for post in _posts_in_category(client, category_seq, per_page):
            seq = post.get("seq")
            if seq is None or seq in seen:
                continue
            seen.add(seq)
            client._cache[seq] = post  # crawl_post 가 소비.
            out.append(
                PostRef(
                    art_no=seq,
                    title=(post.get("title") or "").strip(),
                    author=(post.get("uploader") or None),
                    posted_at=_parse_published(post.get("published_at") or post.get("created_at")),
                    view_count=int(post.get("view_cnt") or 0),
                )
            )
    return out


def _compose_body_html(post: dict[str, Any], video_url: str, base: str) -> str:
    """카테고리·설명·content(HTML)·영상 링크를 본문으로 합본.

    clean_html(run)이 HTML 태그를 제거하므로, 검색·인용에 남겨야 할 영상 링크(/post, 스트리밍)는
    텍스트로도 적는다(URL 이 태그 속성에 갇히면 인덱싱 안 됨). 카테고리는 검색 매칭을 위해 prepend.
    """
    parts: list[str] = []
    group = (post.get("postCategoryGroupName") or "").strip()
    cat = (post.get("postCategoryName") or "").strip()
    label = " > ".join(p for p in (group, cat) if p)
    if label:
        parts.append(f"[카테고리] {label}")
    # ★ load-bearing URL 은 content(무신뢰 HTML)보다 **앞**에 둔다. content 에 미종료
    #   <script>/<style>/주석이 있으면 lxml 이 뒤 텍스트를 그 노드로 흡수→clean_html 이 통째
    #   제거해 영상/HLS URL 이 검색 인덱싱에서 유실되므로(리뷰 Concern ③).
    parts.append(f"영상 보기: {video_url}")
    clip = post.get("clip") or {}
    hls = clip.get("ott_hls_path")
    if hls:
        parts.append(f"스트리밍(HLS): {base}{hls}")
    desc = (post.get("description") or "").strip()
    if desc:
        parts.append(desc)
    content = (post.get("content") or "").strip()
    if content:
        parts.append(content)
    return "\n\n".join(parts)


def crawl_post(client: GaingeClient, board_no: int, ref: PostRef) -> RawPost:
    """캐시(list_post_refs 적재)에서 게시글 dict → 본문 합본 RawPost. 캐시 부재 시 상세 재조회.

    source_url 은 **절대 URL**(gainge_base/post/{seq})로 저장 — build_source/absolute_bizbox_url 이
    이미 http(s) 로 시작하면 그대로 두므로 외부 도메인 절대화 충돌이 없다. attachments=()(영상 무첨부).
    """
    base = client._settings.gainge_base.rstrip("/")
    post = client._cache.get(ref.art_no)
    if post is None:
        # 캐시 부재(단독 재크롤 등) — 카테고리 미상이라 전체 순회로 채운다(드문 경로).
        list_post_refs(client, board_no, None, None, per_page=50)
        post = client._cache.get(ref.art_no) or {}

    video_url = f"{base}/post/{ref.art_no}"
    body_html = _compose_body_html(post, video_url, base)

    return RawPost(
        board_no=board_no,
        art_no=ref.art_no,
        title=ref.title or (post.get("title") or "").strip(),
        body_html=body_html,
        author_name=ref.author or (post.get("uploader") or None),
        author_dept=None,
        posted_at=ref.posted_at or _parse_published(post.get("published_at")),
        view_count=ref.view_count or int(post.get("view_cnt") or 0),
        source_url=video_url,
        attachments=(),
    )
