"""plan §5 — 2-hop iframe 본문 파싱.

viewPost.do HTML → iframe ``bizboxLink.do?url=<urlenc>`` src 추출 → url 파라미터 URL-decode →
실 EDMS 경로 → fetch_inner_content(2-hop) → 진짜 본문. URL 디코드와 2-hop 배선을 검증한다.
"""

from __future__ import annotations

from urllib.parse import quote

from app.ingest.crawler import crawl_post, extract_inner_url

# viewPost.do 응답에 박힌 iframe: bizboxLink.do?url=<urlencoded EDMS 경로>.
_INNER_PATH = "/edms/board/innerView.do?boardNo=1401000286&artNo=1001"
_VIEW_POST_HTML = f"""
<html><body>
  <div class="post-view">
    <h2 class="post-title">출장비 규정</h2>
    <span class="author">홍길동</span>
    <span class="dept">총무팀</span>
    <span class="date">2026-06-20</span>
    <span class="views">123</span>
    <iframe id="_content" src="bizboxLink.do?url={quote(_INNER_PATH, safe='')}"></iframe>
  </div>
</body></html>
"""

_INNER_HTML = """
<html><body><div class="content">
  <p>제1조(목적) 이 규정은 출장비를 정한다.</p>
  <p>①국내출장은 실비로 한다.</p>
</div></body></html>
"""


def test_extract_inner_url_decodes_bizbox_link() -> None:
    inner = extract_inner_url(_VIEW_POST_HTML)
    assert inner == _INNER_PATH


def test_extract_inner_url_none_when_no_iframe() -> None:
    assert extract_inner_url("<html><body>인라인 본문</body></html>") is None


class _StubClient:
    """2-hop 배선 검증용 인라인 스텁(파일/네트워크 없음)."""

    def __init__(self) -> None:
        self.inner_calls: list[str] = []

    def login(self) -> None:  # pragma: no cover - no-op
        pass

    def fetch_post(self, board_no: int, art_no: int) -> str:
        return _VIEW_POST_HTML

    def fetch_inner_content(self, bizbox_link_url: str) -> str:
        self.inner_calls.append(bizbox_link_url)
        return _INNER_HTML

    def fetch_board_page(self, board_no, page, per_page):  # pragma: no cover
        return ""

    def download_attachment(self, url, params):  # pragma: no cover
        return b""


def test_crawl_post_fetches_inner_content_via_second_hop() -> None:
    client = _StubClient()
    raw = crawl_post(client, board_no=1401000286, art_no=1001)

    # 2-hop: 디코드된 실경로로 fetch_inner_content 가 호출됐다.
    assert client.inner_calls == [_INNER_PATH]
    # 본문은 1-hop viewPost 가 아니라 2-hop inner content.
    assert "제1조" in raw.body_html
    # 메타는 1-hop viewPost 에서.
    assert raw.title == "출장비 규정"
    assert raw.author_name == "홍길동"
    assert raw.author_dept == "총무팀"
    assert raw.view_count == 123
    assert raw.posted_at is not None and raw.posted_at.year == 2026
