"""보드 순회·목록/글 파싱·2-hop 본문 (plan §2·§5). HTML→raw dataclass.

- ``list_post_refs``: 목록 HTML 표 파싱 → 워터마크 초과분만(최신순, 워터마크 도달 시 조기종료).
- ``extract_inner_url``: viewPost HTML 의 iframe ``bizboxLink.do?url=<urlenc>`` → 디코드된 실경로.
- ``crawl_post``: viewPost 메타 + 2-hop 본문 + 첨부 ref 파싱 → ``RawPost``.

bs4/lxml 파싱. 본문 정제(clean_html)·content_hash 는 호출부(run)가 적용한다 — 여기는 raw HTML 까지.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import BeautifulSoup

from app.ingest.models import PostRef, RawAttachment, RawPost

if TYPE_CHECKING:
    from app.ingest.bizbox_client import BizboxClient

_VIEW_POST_RE = re.compile(r"viewPost\(\s*(\d+)\s*\)")
_DATE_RE = re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")
_DIGITS_RE = re.compile(r"\d+")

# 확장자 → attachment.kind CHECK enum.
_EXT_KIND = {
    "hwp": "hwp", "hwpx": "hwp",
    "pdf": "pdf",
    "xlsx": "excel", "xls": "excel", "xlsm": "excel",
    "png": "image", "jpg": "image", "jpeg": "image", "gif": "image",
    "tif": "image", "tiff": "image", "bmp": "image",
    "doc": "word", "docx": "word",
}

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


def _kind_from_ext(ext: str | None) -> str:
    return _EXT_KIND.get((ext or "").lower().lstrip("."), "etc")


# ── 목록 ─────────────────────────────────────────────────────────────────────


def _parse_list_rows(html: str) -> list[PostRef]:
    """목록 HTML 표 → PostRef 목록(표 출현순 = 최신순 가정)."""
    soup = BeautifulSoup(html, "lxml")
    refs: list[PostRef] = []
    for tr in soup.select("tr"):
        row_html = str(tr)
        m = _VIEW_POST_RE.search(row_html)
        if not m:
            continue
        art_no = int(m.group(1))
        tds = tr.find_all("td")
        cells = [td.get_text(" ", strip=True) for td in tds]
        title = ""
        link = tr.find("a")
        if link:
            title = link.get_text(" ", strip=True)
        # 작성자: 'author' 클래스 우선, 없으면 위치(3번째 셀).
        author = None
        author_td = tr.find("td", class_="author")
        if author_td:
            author = author_td.get_text(" ", strip=True)
        elif len(cells) >= 3:
            author = cells[2]
        # 등록일: 날짜 패턴이 있는 셀.
        posted_at = None
        for c in cells:
            posted_at = _parse_date(c)
            if posted_at:
                break
        refs.append(PostRef(art_no=art_no, title=title, author=author or None, posted_at=posted_at))
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

    페이지 1부터 순회하며, 한 페이지에서 워터마크 이하 글을 만나면 더 이상 페이지를 받지 않는다
    (목록이 최신순 정렬이므로 이후는 모두 수집분). 워터마크가 없으면(--full/최초) 빈 페이지까지.
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


# ── 2-hop ────────────────────────────────────────────────────────────────────


def extract_inner_url(view_post_html: str) -> str | None:
    """viewPost HTML 의 iframe ``bizboxLink.do?url=<urlenc>`` → URL-decode 된 실경로.

    iframe 이 없거나 url 파라미터가 없으면 None(2-hop 불필요, 인라인 본문).
    """
    soup = BeautifulSoup(view_post_html, "lxml")
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src") or ""
        if "bizboxLink.do" not in src and "url=" not in src:
            continue
        query = urlsplit(src).query
        url_vals = parse_qs(query).get("url")
        if url_vals:
            return unquote(url_vals[0])
    return None


def _parse_attachments(soup: BeautifulSoup, board_no: int) -> list[RawAttachment]:
    """첨부 ref 파싱. 파일 링크의 data-* 필드(DESIGN §7) → RawAttachment.

    필드: fileNm/fileRnm/filePath/saveFileName/orignlFileName/fileExt/fileSeq.
    download_url 은 링크 href 우선, 없으면 메인 다운로드 경로 + saveFileName 으로 합성.
    """
    atts: list[RawAttachment] = []
    for el in soup.select("a.file, .attachments a, [data-filenm], [data-savefilename]"):
        data = {k.lower(): v for k, v in el.attrs.items()}
        file_nm = (
            data.get("data-filenm")
            or data.get("data-orignlfilename")
            or el.get_text(" ", strip=True)
        )
        if not file_nm:
            continue
        save_name = data.get("data-savefilename") or file_nm
        ext = data.get("data-fileext")
        if not ext and "." in file_nm:
            ext = file_nm.rsplit(".", 1)[1]
        seq = data.get("data-fileseq")
        href = el.get("href")
        if href and href.startswith("javascript:"):
            href = None
        download_url = href or (
            f"/gw/cmm/file/edmsDownloadProc.do?boardNo={board_no}&saveFileName={save_name}"
        )
        atts.append(
            RawAttachment(
                file_name=file_nm,
                kind=_kind_from_ext(ext),
                bizbox_file_seq=int(seq) if seq and seq.isdigit() else None,
                download_url=download_url,
                file_ext=ext.lower() if ext else None,
            )
        )
    return atts


def _meta_text(soup: BeautifulSoup, selector: str) -> str | None:
    el = soup.select_one(selector)
    return el.get_text(" ", strip=True) if el else None


def crawl_post(client: BizboxClient, board_no: int, art_no: int) -> RawPost:
    """viewPost.do → 메타 + 2-hop 본문 + 첨부 ref → RawPost.

    body_text(정제)·content_hash 는 호출부(run)가 채운다 — 여기는 raw body_html 까지.
    """
    view_html = client.fetch_post(board_no, art_no)
    soup = BeautifulSoup(view_html, "lxml")

    title = (
        _meta_text(soup, ".post-title")
        or _meta_text(soup, "h1")
        or _meta_text(soup, "h2")
        or ""
    )
    author = _meta_text(soup, ".author")
    dept = _meta_text(soup, ".dept")
    posted_at = _parse_date(_meta_text(soup, ".date"))
    views_text = _meta_text(soup, ".views") or ""
    views_m = _DIGITS_RE.search(views_text)
    view_count = int(views_m.group()) if views_m else 0

    inner_url = extract_inner_url(view_html)
    if inner_url is not None:
        body_html = client.fetch_inner_content(inner_url)
    else:
        body_el = soup.select_one(".post-body, .content, .post-view")
        body_html = str(body_el) if body_el else view_html

    attachments = _parse_attachments(soup, board_no)
    source_url = f"/edms/board/viewPost.do?boardNo={board_no}&artNo={art_no}"

    return RawPost(
        board_no=board_no,
        art_no=art_no,
        title=title,
        body_html=body_html,
        author_name=author,
        author_dept=dept,
        posted_at=posted_at,
        view_count=view_count,
        source_url=source_url,
        attachments=tuple(attachments),
    )
