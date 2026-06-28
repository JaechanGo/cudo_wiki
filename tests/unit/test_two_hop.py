"""plan §5 — 2-hop 본문 파싱 (라이브 실측 구조).

viewPost.do HTML → 본문 iframe ``viewPostArtContent.do?boardNo=&artNo=`` 경로 추출 →
fetch_inner_content(2-hop) → 진짜 본문. 메타(title/author/...)는 목록 ``PostRef`` 재사용.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ingest.crawler import crawl_post, extract_inner_url
from app.ingest.models import PostRef

# viewPost.do 응답에 박힌 본문 iframe: viewPostArtContent.do (구 bizboxLink.do 폐기).
_VIEW_POST_HTML = """
<html><body>
  <div class="post-view">
    <iframe id="contentIframe"
            src="viewPostArtContent.do?boardNo=900000286&artNo=1001"></iframe>
  </div>
</body></html>
"""

_INNER_HTML = """
<html><head><style>p{font-size:12px;}</style></head><body><div class="contents">
  <p>제1조(목적) 이 규정은 출장비를 정한다.</p>
  <p>①국내출장은 실비로 한다.</p>
</div></body></html>
"""


def test_extract_inner_url_builds_art_content_path() -> None:
    inner = extract_inner_url(_VIEW_POST_HTML)
    assert inner == "/edms/board/viewPostArtContent.do?boardNo=900000286&artNo=1001"


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

    def fetch_inner_content(self, inner_url: str) -> str:
        self.inner_calls.append(inner_url)
        return _INNER_HTML

    def fetch_board_page(self, board_no, page, per_page):  # pragma: no cover
        return ""

    def download_attachment(self, url, params):  # pragma: no cover
        return b""


def test_crawl_post_fetches_inner_content_via_second_hop() -> None:
    client = _StubClient()
    ref = PostRef(
        art_no=1001, title="출장비 규정", author="홍길동",
        posted_at=datetime(2026, 6, 20, tzinfo=UTC), view_count=123, has_attachment=False,
    )
    raw = crawl_post(client, 900000286, ref)

    # 2-hop: viewPostArtContent 실경로로 fetch_inner_content 가 호출됐다.
    assert client.inner_calls == ["/edms/board/viewPostArtContent.do?boardNo=900000286&artNo=1001"]
    # 본문은 1-hop viewPost 가 아니라 2-hop inner content.
    assert "제1조" in raw.body_html
    # 메타는 목록 ref 에서 재사용(viewPost HTML 재파싱 안 함).
    assert raw.title == "출장비 규정"
    assert raw.author_name == "홍길동"
    assert raw.view_count == 123
    assert raw.posted_at is not None and raw.posted_at.year == 2026
    assert raw.source_url == "/edms/board/viewPost.do?boardNo=900000286&artNo=1001"


def test_crawl_post_inline_body_when_no_iframe() -> None:
    """본문 iframe 이 없으면 viewPost HTML 자체를 본문으로 사용(폴백)."""
    class _Inline(_StubClient):
        def fetch_post(self, board_no, art_no):
            return "<html><body><div class='contents'>인라인 규정 본문</div></body></html>"

    ref = PostRef(art_no=1001, title="T", author=None, posted_at=None)
    raw = crawl_post(_Inline(), 900000286, ref)
    assert "인라인 규정 본문" in raw.body_html
