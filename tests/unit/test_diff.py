"""diff.compute_clause_diff 단위테스트 (Task009 §3.7·§8.1).

조항(canonical_clause_id) 키로 두 규정의 clause 집합 대조 — added/removed/changed. 직전판 부재
(from 비어있음)는 added-only(전체 신규). text 비교는 공백 정규화 후.
"""

from __future__ import annotations

from app.mcp.diff import ClauseChange, ClauseRef, ClauseRow, compute_clause_diff


def _row(cid, label, text):
    return ClauseRow(canonical_clause_id=cid, clause_label=label, text=text)


def test_added_only_when_from_empty():
    """직전판 부재 → 현행 전체가 added."""
    to_rows = [_row("C1", "제1조", "본문1"), _row("C2", "제2조", "본문2")]
    diff = compute_clause_diff([], to_rows)
    assert diff.added == [ClauseRef("C1", "제1조"), ClauseRef("C2", "제2조")]
    assert diff.removed == []
    assert diff.changed == []


def test_removed_clause():
    from_rows = [_row("C1", "제1조", "본문1"), _row("C2", "제2조", "본문2")]
    to_rows = [_row("C1", "제1조", "본문1")]
    diff = compute_clause_diff(from_rows, to_rows)
    assert diff.removed == [ClauseRef("C2", "제2조")]
    assert diff.added == []
    assert diff.changed == []


def test_added_clause():
    from_rows = [_row("C1", "제1조", "본문1")]
    to_rows = [_row("C1", "제1조", "본문1"), _row("C3", "제3조", "신규")]
    diff = compute_clause_diff(from_rows, to_rows)
    assert diff.added == [ClauseRef("C3", "제3조")]
    assert diff.removed == []
    assert diff.changed == []


def test_changed_clause_text_differs():
    from_rows = [_row("C1", "제1조", "옛 본문")]
    to_rows = [_row("C1", "제1조", "새 본문")]
    diff = compute_clause_diff(from_rows, to_rows)
    assert diff.changed == [ClauseChange("C1", "제1조", "옛 본문", "새 본문")]
    assert diff.added == []
    assert diff.removed == []


def test_identical_text_not_changed():
    from_rows = [_row("C1", "제1조", "동일 본문")]
    to_rows = [_row("C1", "제1조", "동일 본문")]
    diff = compute_clause_diff(from_rows, to_rows)
    assert diff.changed == []


def test_whitespace_only_diff_not_changed():
    """공백 정규화 후 동일하면 변경 아님(오탐 방지)."""
    from_rows = [_row("C1", "제1조", "본문  내용")]
    to_rows = [_row("C1", "제1조", "본문 내용 ")]
    diff = compute_clause_diff(from_rows, to_rows)
    assert diff.changed == []


def test_combined_added_removed_changed():
    from_rows = [_row("C1", "제1조", "A"), _row("C2", "제2조", "B")]
    to_rows = [_row("C1", "제1조", "A-수정"), _row("C3", "제3조", "C")]
    diff = compute_clause_diff(from_rows, to_rows)
    assert diff.added == [ClauseRef("C3", "제3조")]
    assert diff.removed == [ClauseRef("C2", "제2조")]
    assert diff.changed == [ClauseChange("C1", "제1조", "A", "A-수정")]


def test_output_order_is_deterministic():
    """입력 순서(SQL order_seq 정렬) 보존 → 결정론."""
    to_rows = [_row("C3", "제3조", "x"), _row("C1", "제1조", "y"), _row("C2", "제2조", "z")]
    diff = compute_clause_diff([], to_rows)
    assert [r.canonical_clause_id for r in diff.added] == ["C3", "C1", "C2"]
