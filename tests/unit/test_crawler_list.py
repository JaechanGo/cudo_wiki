"""plan §2·§4 — 목록 표 파싱 + 워터마크 증분 델타 + 조기종료.

목록 HTML 표(번호·제목·작성자·조회·좋아요·등록일)를 파싱해 ``PostRef`` 로 만들고, 워터마크
(``since_art_no``) 초과분만 최신순으로 반환하며 워터마크 도달 시 조기 종료하는지 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ingest.crawler import list_post_refs

# 최신순(내림차순) 목록: artNo 1003 > 1002 > 1001.
_BOARD_P1 = """
<table class="board-list"><tbody>
  <tr>
    <td class="num">1003</td>
    <td class="title"><a href="javascript:viewPost(1003)">규정 개정 안내</a></td>
    <td class="author">홍길동</td><td class="views">10</td>
    <td class="likes">0</td><td class="date">2026-06-22</td>
  </tr>
  <tr>
    <td class="num">1002</td>
    <td class="title"><a href="javascript:viewPost(1002)">출장비 규정</a></td>
    <td class="author">김철수</td><td class="views">25</td>
    <td class="likes">1</td><td class="date">2026-06-20</td>
  </tr>
  <tr>
    <td class="num">1001</td>
    <td class="title"><a href="javascript:viewPost(1001)">복무 규정</a></td>
    <td class="author">이영희</td><td class="views">42</td>
    <td class="likes">2</td><td class="date">2026-06-18</td>
  </tr>
</tbody></table>
"""


class _ListStub:
    """페이지 1만 목록을 주고, 이후 페이지는 빈 표(조기종료 경로 검증)."""

    def __init__(self) -> None:
        self.pages_fetched: list[int] = []

    def login(self) -> None:  # pragma: no cover
        pass

    def fetch_board_page(self, board_no: int, page: int, per_page: int) -> str:
        self.pages_fetched.append(page)
        return _BOARD_P1 if page == 1 else "<table class='board-list'><tbody></tbody></table>"


def test_list_parses_all_rows_when_no_watermark() -> None:
    refs = list_post_refs(_ListStub(), board_no=1401000286, since_art_no=None, since_posted_at=None)
    assert [r.art_no for r in refs] == [1003, 1002, 1001]
    assert refs[0].title == "규정 개정 안내"
    assert refs[0].author == "홍길동"
    assert refs[1].posted_at == datetime(2026, 6, 20, tzinfo=UTC)


def test_list_returns_only_above_watermark() -> None:
    refs = list_post_refs(_ListStub(), board_no=1401000286, since_art_no=1001, since_posted_at=None)
    # 1001 은 워터마크와 같음(이미 수집) → 제외. 1002·1003 만 델타.
    assert [r.art_no for r in refs] == [1003, 1002]


def test_list_early_stops_at_watermark_without_extra_pages() -> None:
    """워터마크 도달 시 다음 페이지를 추가로 가져오지 않는다(조기종료)."""
    stub = _ListStub()
    refs = list_post_refs(stub, board_no=1401000286, since_art_no=1002, since_posted_at=None)
    assert [r.art_no for r in refs] == [1003]
    # 1페이지에서 워터마크(1002) 도달 → 2페이지 fetch 안 함.
    assert stub.pages_fetched == [1]


def test_list_full_recrawl_paginates_until_empty() -> None:
    """워터마크 없으면 빈 페이지가 나올 때까지 순회(페이지2까지 fetch)."""
    stub = _ListStub()
    list_post_refs(stub, board_no=1401000286, since_art_no=None, since_posted_at=None)
    assert stub.pages_fetched == [1, 2]
