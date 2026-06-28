"""규정 개정 diff — 조항 집합 비교 (Task009 plan §3.7).

비교 단위 = 조항(canonical_clause_id). 두 규정의 현행 clause 집합을 키로 대조해 added/removed
/changed 산출. text 비교는 공백 정규화 후(서식 차이를 변경으로 오탐 안 함). 순수 함수 — DB 조회
(supersedes 체인·clause 적재)는 도구 핸들러가 수행하고 결과 행만 본 함수에 주입한다(테스트 용이).

직전판 부재(최초판)는 도구 레벨에서 ``from_rows=[]`` 로 호출 → 전체 added(``is_initial`` 플래그는
도구 출력에서 부착).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class ClauseRow:
    """비교 입력 1행 — DB 조회 결과를 담는 경량 구조."""

    canonical_clause_id: str
    clause_label: str | None
    text: str


@dataclass(frozen=True)
class ClauseRef:
    """added/removed 참조 — 조항 식별자 + 라벨."""

    canonical_clause_id: str
    clause_label: str | None


@dataclass(frozen=True)
class ClauseChange:
    """changed 항목 — 변경 전/후 본문(레닥션은 도구 출력에서)."""

    canonical_clause_id: str
    clause_label: str | None
    before: str
    after: str


@dataclass(frozen=True)
class ClauseDiff:
    """compute_clause_diff 결과."""

    added: list[ClauseRef]
    removed: list[ClauseRef]
    changed: list[ClauseChange]


def _norm(text: str) -> str:
    """본문 비교용 정규화 — 연속 공백 1칸·양끝 trim."""
    return _WS.sub(" ", text).strip()


def compute_clause_diff(
    from_rows: list[ClauseRow], to_rows: list[ClauseRow]
) -> ClauseDiff:
    """from→to 조항 집합 diff. added=to 전용, removed=from 전용, changed=양쪽 존재 & 본문 상이.

    출력 순서는 입력 순서를 보존(SQL ORDER BY order_seq → 결정론).
    """
    from_by_id = {r.canonical_clause_id: r for r in from_rows}
    to_by_id = {r.canonical_clause_id: r for r in to_rows}

    added: list[ClauseRef] = []
    changed: list[ClauseChange] = []
    for row in to_rows:
        prev = from_by_id.get(row.canonical_clause_id)
        if prev is None:
            added.append(ClauseRef(row.canonical_clause_id, row.clause_label))
        elif _norm(prev.text) != _norm(row.text):
            changed.append(
                ClauseChange(row.canonical_clause_id, row.clause_label, prev.text, row.text)
            )

    removed: list[ClauseRef] = [
        ClauseRef(row.canonical_clause_id, row.clause_label)
        for row in from_rows
        if row.canonical_clause_id not in to_by_id
    ]

    return ClauseDiff(added=added, removed=removed, changed=changed)
