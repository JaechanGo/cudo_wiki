"""보드 순회·목록/글 파싱·2-hop 본문 (plan §2·§5, DESIGN §7 라이브 실측 2026-06-29).

라이브 BizBox(다우오피스 EDMS) 실측 계약:
- ``list_post_refs``: ``viewBoard.do`` 응답의 인라인 JS 배열 ``var exData = [ {...}, ... ];``
  파싱(목록 행은 ``<table>`` 이 아니라 클라이언트 JS 템플릿이 그리는 데이터). 워터마크 초과분만.
- ``extract_inner_url``: viewPost HTML 의 본문 iframe ``viewPostArtContent.do?boardNo=&artNo=``
  (구 bizboxLink.do 가정 폐기) → 2-hop 실 본문 경로.
- ``crawl_post``: viewPost(메타는 목록 ``PostRef`` 재사용) + 2-hop 본문 → ``RawPost``.
  첨부(``appendFileTop.do`` + ``download.do``)는 boardNo/artNo 동적주입 구조라 1차 생략(후속).

bs4/lxml + json 파싱. 본문 정제(clean_html)·content_hash 는 호출부(run)가 적용 — 여기는 raw 까지.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.ingest.models import PostRef, RawPost

if TYPE_CHECKING:
    from app.ingest.bizbox_client import BizboxClient

_DATE_RE = re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")

# viewBoard.do 응답의 인라인 목록 데이터: ``var exData = [ ... ];`` (최신순).
_EXDATA_RE = re.compile(r"var\s+exData\s*=\s*(\[.*?\])\s*;", re.S)
# JS 객체 리터럴의 트레일링 콤마(`,]` `,}`) → JSON 파서가 거부하므로 제거.
_TRAILING_COMMA_RE = re.compile(r",(\s*[\]}])")
# viewPost HTML 의 2-hop 본문 iframe 경로.
_INNER_RE = re.compile(r"viewPostArtContent\.do\?([^\"'\s>]+)")

_MAX_PAGES = 200  # --full 무한루프 방지(plan §4 페이지네이션 안전캡).


def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
    except ValueError:
        return None


def _to_int(value: object) -> int:
    """read_cnt 등 문자열/정수 혼재 필드 → int(실패 시 0)."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


# ── 목록 (exData JSON) ────────────────────────────────────────────────────────


def _parse_exdata(html: str) -> list[dict]:
    """viewBoard.do 응답에서 ``var exData = [...]`` 추출 → dict 리스트."""
    m = _EXDATA_RE.search(html)
    if not m:
        return []
    raw = _TRAILING_COMMA_RE.sub(r"\1", m.group(1))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def _row_to_ref(d: dict) -> PostRef | None:
    """exData 1요소 → PostRef. art_seq_no 없으면 None(공지 placeholder 등)."""
    art = d.get("art_seq_no")
    if art is None:
        return None
    try:
        art_no = int(art)
    except (TypeError, ValueError):
        return None
    return PostRef(
        art_no=art_no,
        title=(d.get("art_title") or "").strip(),
        author=(d.get("mbr_nick") or None),
        posted_at=_parse_date(d.get("write_date")),
        view_count=_to_int(d.get("read_cnt")),
        has_attachment=(d.get("add_file_yn") == "Y"),
    )


def _parse_list_rows(html: str) -> list[PostRef]:
    """목록 HTML(exData JSON) → PostRef 목록(배열 출현순 = 최신순)."""
    refs: list[PostRef] = []
    for d in _parse_exdata(html):
        ref = _row_to_ref(d)
        if ref is not None:
            refs.append(ref)
    return refs


def list_post_refs(
    client: BizboxClient,
    board_no: int,
    since_art_no: int | None,
    since_posted_at: datetime | None,
    *,
    per_page: int = 50,
) -> list[PostRef]:
    """목록 순회 → 워터마크 초과 PostRef(최신순). 워터마크 도달 시 조기종료(plan §4).

    exData 는 art_seq_no 내림차순(최신 먼저)이므로, 워터마크 이하 글을 처음 만나면
    이후 페이지는 모두 수집분 → 더 받지 않는다(--full/최초는 빈 페이지까지).
    """
    out: list[PostRef] = []
    page = 1
    while page <= _MAX_PAGES:
        html = client.fetch_board_page(board_no, page, per_page)
        rows = _parse_list_rows(html)
        if not rows:
            break
        reached_watermark = False
        for ref in rows:
            if since_art_no is not None and ref.art_no <= since_art_no:
                reached_watermark = True
                break
            if (
                since_posted_at is not None
                and ref.posted_at is not None
                and ref.posted_at <= since_posted_at
            ):
                reached_watermark = True
                break
            out.append(ref)
        if reached_watermark:
            break  # 조기종료 — 다음 페이지 fetch 안 함.
        page += 1
    return out


# ── 2-hop 본문 ────────────────────────────────────────────────────────────────


def extract_inner_url(view_post_html: str) -> str | None:
    """viewPost HTML 의 본문 iframe ``viewPostArtContent.do?boardNo=&artNo=`` 실경로.

    iframe 이 없으면 None(인라인 본문 → 호출부가 viewPost HTML 자체를 본문으로 사용).
    """
    m = _INNER_RE.search(view_post_html)
    if not m:
        return None
    return "/edms/board/viewPostArtContent.do?" + m.group(1)


def crawl_post(client: BizboxClient, board_no: int, ref: PostRef) -> RawPost:
    """viewPost.do(메타는 ``ref`` 재사용) + 2-hop 본문(viewPostArtContent.do) → RawPost.

    body_text(정제)·content_hash 는 호출부(run)가 채운다 — 여기는 raw body_html 까지.
    첨부는 1차 미수집(빈 tuple) — appendFileTop.do/download.do 라이브 파싱은 후속(DESIGN §7).
    """
    view_html = client.fetch_post(board_no, ref.art_no)

    inner_url = extract_inner_url(view_html)
    body_html = client.fetch_inner_content(inner_url) if inner_url is not None else view_html

    source_url = f"/edms/board/viewPost.do?boardNo={board_no}&artNo={ref.art_no}"

    return RawPost(
        board_no=board_no,
        art_no=ref.art_no,
        title=ref.title,
        body_html=body_html,
        author_name=ref.author,
        author_dept=None,  # 부서는 viewPost 페이지 파싱 영역(후속) — 목록 JSON 엔 없음.
        posted_at=ref.posted_at,
        view_count=ref.view_count,
        source_url=source_url,
        attachments=(),
    )
