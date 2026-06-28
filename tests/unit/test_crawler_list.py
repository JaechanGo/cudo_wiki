"""plan §2·§4 — 목록 파싱(라이브 exData JSON) + 워터마크 증분 델타 + 조기종료.

라이브 BizBox 실측: 목록 행은 ``<table>`` 이 아니라 viewBoard.do 응답에 임베드된 인라인
JS 배열 ``var exData = [ {...}, ... ];`` 이다. 이를 파싱해 ``PostRef`` 로 만들고, 워터마크
(``since_art_no``) 초과분만 최신순으로 반환하며 워터마크 도달 시 조기 종료하는지 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ingest.crawler import list_post_refs

# 최신순(내림차순) 목록: art_seq_no 1003 > 1002 > 1001. 라이브 viewBoard.do 의 인라인 exData.
_BOARD_P1 = """
<script type="text/javascript">
j$(document).ready(function(){
  var exData = [
    { "art_seq_no": 1003, "art_parent_no": 1003, "notice_yn": "N", "art_read_yn": "Y",
      "add_file_yn": "N", "img_file_yn": "N", "is_new_yn": "N", "num": "3",
      "art_remark": "분류 없음", "art_title": "규정 개정 안내", "mbr_nick": "홍길동",
      "read_cnt": "10", "recomm_cnt": "0", "reply_cnt": 0, "write_date": "2026-06-22" }
    ,
    { "art_seq_no": 1002, "art_parent_no": 1002, "notice_yn": "N", "art_read_yn": "N",
      "add_file_yn": "Y", "img_file_yn": "N", "is_new_yn": "N", "num": "2",
      "art_remark": "분류 없음", "art_title": "출장비 규정", "mbr_nick": "김철수",
      "read_cnt": "25", "recomm_cnt": "1", "reply_cnt": 0, "write_date": "2026-06-20" }
    ,
    { "art_seq_no": 1001, "art_parent_no": 1001, "notice_yn": "N", "art_read_yn": "Y",
      "add_file_yn": "N", "img_file_yn": "N", "is_new_yn": "N", "num": "1",
      "art_remark": "분류 없음", "art_title": "복무 규정", "mbr_nick": "이영희",
      "read_cnt": "42", "recomm_cnt": "2", "reply_cnt": 0, "write_date": "2026-06-18" }
  ];
});
</script>
"""

# 빈 페이지: exData 가 빈 배열(라이브에서 마지막 페이지 이후).
_BOARD_EMPTY = '<script>var exData = [];</script>'


class _ListStub:
    """페이지 1만 목록을 주고, 이후 페이지는 빈 exData(조기종료 경로 검증)."""

    def __init__(self) -> None:
        self.pages_fetched: list[int] = []

    def login(self) -> None:  # pragma: no cover
        pass

    def fetch_board_page(self, board_no: int, page: int, per_page: int) -> str:
        self.pages_fetched.append(page)
        return _BOARD_P1 if page == 1 else _BOARD_EMPTY


def test_list_parses_all_rows_when_no_watermark() -> None:
    refs = list_post_refs(_ListStub(), board_no=900000286, since_art_no=None, since_posted_at=None)
    assert [r.art_no for r in refs] == [1003, 1002, 1001]
    assert refs[0].title == "규정 개정 안내"
    assert refs[0].author == "홍길동"
    assert refs[0].view_count == 10
    assert refs[1].posted_at == datetime(2026, 6, 20, tzinfo=UTC)
    assert refs[1].has_attachment is True  # add_file_yn == "Y"
    assert refs[0].has_attachment is False


def test_list_returns_only_above_watermark() -> None:
    refs = list_post_refs(_ListStub(), board_no=900000286, since_art_no=1001, since_posted_at=None)
    # 1001 은 워터마크와 같음(이미 수집) → 제외. 1002·1003 만 델타.
    assert [r.art_no for r in refs] == [1003, 1002]


def test_list_early_stops_at_watermark_without_extra_pages() -> None:
    """워터마크 도달 시 다음 페이지를 추가로 가져오지 않는다(조기종료)."""
    stub = _ListStub()
    refs = list_post_refs(stub, board_no=900000286, since_art_no=1002, since_posted_at=None)
    assert [r.art_no for r in refs] == [1003]
    # 1페이지에서 워터마크(1002) 도달 → 2페이지 fetch 안 함.
    assert stub.pages_fetched == [1]


def test_list_full_recrawl_paginates_until_empty() -> None:
    """워터마크 없으면 빈 페이지가 나올 때까지 순회(페이지2까지 fetch)."""
    stub = _ListStub()
    list_post_refs(stub, board_no=900000286, since_art_no=None, since_posted_at=None)
    assert stub.pages_fetched == [1, 2]
