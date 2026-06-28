"""plan §6 — xlsx 전결표 셀 추출 → authority cells dict (authority_parser 입력 호환).

openpyxl 로 합성 xlsx 를 메모리에 만들고, ``extract_excel_cells`` 가 헤더 행을 인식해
각 데이터 행을 파트1 인계 스키마(business_item·action_type·amount_expr·consulter_roles·...)
dict 로 산출하는지 검증한다. 산출 dict 는 그대로 ``parse_authority_matrix`` 에 넘어간다.
"""

from __future__ import annotations

import io

import openpyxl

from app.ingest.authority_parser import parse_authority_matrix
from app.ingest.extract.excel import extract_excel_cells, extract_excel_text


def _xlsx_bytes(rows: list[list[str]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_HEADER = ["대분류", "업무항목", "결재구분", "금액기준", "전결권자", "합의", "비고"]
_ROWS = [
    _HEADER,
    ["총무", "비품구매", "전결", "1천만원 이하", "팀장", "재무팀/구매팀", "긴급시 사후"],
    ["총무", "비품구매", "합의", "1천만원 초과", "본부장", "재무팀", ""],
]


def test_excel_cells_map_headers_to_authority_fields() -> None:
    cells = extract_excel_cells(_xlsx_bytes(_ROWS))

    assert len(cells) == 2
    first = cells[0]
    assert first["business_category"] == "총무"
    assert first["business_item"] == "비품구매"
    assert first["action_type"] == "전결"
    assert first["amount_expr"] == "1천만원 이하"
    assert first["approver_role"] == "팀장"
    assert first["consulter_roles"] == ["재무팀", "구매팀"]
    assert first["condition_note"] == "긴급시 사후"
    assert first["order_seq"] == 0
    assert cells[1]["order_seq"] == 1


def test_excel_cells_feed_authority_parser() -> None:
    """산출 cells 가 parse_authority_matrix 입력으로 그대로 호환(end-to-end)."""
    cells = extract_excel_cells(_xlsx_bytes(_ROWS))
    parsed = parse_authority_matrix(cells, regulation_id=742)

    assert len(parsed) == 2
    assert parsed[0].canonical_authority_id == "R742#auth0"
    assert parsed[0].amount_min is None
    assert parsed[0].amount_max == 10_000_000
    assert parsed[0].consulter_roles == ("재무팀", "구매팀")
    # "초과" 보정: 1천만원 초과 → min = 10_000_001.
    assert parsed[1].amount_min == 10_000_001
    assert parsed[1].amount_max is None


def test_excel_skips_blank_rows() -> None:
    rows = [_HEADER, ["", "", "", "", "", "", ""], _ROWS[1]]
    cells = extract_excel_cells(_xlsx_bytes(rows))
    assert len(cells) == 1
    assert cells[0]["business_item"] == "비품구매"


def test_excel_text_dump_contains_values() -> None:
    text = extract_excel_text(_xlsx_bytes(_ROWS))
    assert "비품구매" in text
    assert "전결" in text
