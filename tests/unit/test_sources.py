"""sources.assemble_source_meta 단위테스트 (Task009 §6·§8.1).

출처메타는 LLM 미관여 결정론 조립. 동일 입력 → 동일 출력, 첨부는 attachment_id 오름차순 고정 정렬.
"""

from __future__ import annotations

from datetime import date

from app.mcp.schemas import AttachmentRef, SourceMeta
from app.mcp.sources import assemble_source_meta


def test_assembles_basic_fields():
    meta = assemble_source_meta(
        board_id=3,
        board_name="규정",
        post_id=7,
        title="인사규정",
        reg_code="REG-001",
        effective_date=date(2024, 1, 1),
        source_url="http://gw/post/7",
        attachment_rows=[],
    )
    assert isinstance(meta, SourceMeta)
    assert meta.board_id == 3
    assert meta.board_name == "규정"
    assert meta.post_id == 7
    assert meta.title == "인사규정"
    assert meta.reg_code == "REG-001"
    assert meta.effective_date == date(2024, 1, 1)
    assert meta.source_url == "http://gw/post/7"
    assert meta.attachments == []


def test_attachments_sorted_by_id():
    rows = [
        {"attachment_id": 30, "file_name": "c.pdf", "kind": "pdf", "download_url": "u30"},
        {"attachment_id": 10, "file_name": "a.hwp", "kind": "hwp", "download_url": "u10"},
        {"attachment_id": 20, "file_name": "b.xlsx", "kind": "excel", "download_url": None},
    ]
    meta = assemble_source_meta(
        board_id=1, board_name="b", post_id=1, title="t",
        reg_code=None, effective_date=None, source_url=None, attachment_rows=rows,
    )
    assert [a.attachment_id for a in meta.attachments] == [10, 20, 30]
    assert meta.attachments[0] == AttachmentRef(
        attachment_id=10, file_name="a.hwp", kind="hwp", download_url="u10"
    )


def test_deterministic_same_input_same_output():
    rows = [{"attachment_id": 5, "file_name": "x", "kind": "pdf", "download_url": "u"}]
    kwargs = dict(
        board_id=1, board_name="b", post_id=2, title="t",
        reg_code="R", effective_date=date(2023, 6, 1), source_url="s", attachment_rows=rows,
    )
    assert assemble_source_meta(**kwargs) == assemble_source_meta(**kwargs)


def test_optional_post_id_none():
    meta = assemble_source_meta(
        board_id=1, board_name="b", post_id=None, title="t",
        reg_code=None, effective_date=None, source_url=None, attachment_rows=[],
    )
    assert meta.post_id is None
