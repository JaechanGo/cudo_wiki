"""acl.filter_board_ids 단위테스트 (Task009 §4.3·§8.1).

요청 보드 ∩ 허용 보드 = 유효 보드. 요청에 비허용/미존재 보드가 있으면 drop + denied 로 추적
(민감보드 요청 감사용). requested=None 이면 허용 전체.
"""

from __future__ import annotations

from app.mcp.acl import filter_board_ids


def test_none_requested_returns_all_allowed():
    eff, denied = filter_board_ids(None, [1, 2, 3])
    assert eff == [1, 2, 3]
    assert denied == []


def test_intersection():
    eff, denied = filter_board_ids([2, 3], [1, 2, 3, 4])
    assert eff == [2, 3]
    assert denied == []


def test_denied_board_dropped():
    """요청한 99(민감/미존재)는 drop + denied 기록."""
    eff, denied = filter_board_ids([2, 99], [1, 2, 3])
    assert eff == [2]
    assert denied == [99]


def test_all_denied():
    eff, denied = filter_board_ids([98, 99], [1, 2, 3])
    assert eff == []
    assert denied == [98, 99]


def test_empty_allowed_denies_everything():
    eff, denied = filter_board_ids([1, 2], [])
    assert eff == []
    assert denied == [1, 2]


def test_preserves_request_order_and_dedupes():
    eff, denied = filter_board_ids([3, 1, 3], [1, 2, 3])
    assert eff == [3, 1]
    assert denied == []


def test_empty_requested_list_is_empty_effective():
    """빈 리스트 명시(=아무 보드도 요청 안 함)는 None 과 구분 — 빈 결과."""
    eff, denied = filter_board_ids([], [1, 2, 3])
    assert eff == []
    assert denied == []
