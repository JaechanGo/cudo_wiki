"""clause_parser 단위테스트 (DB 불필요 — plan §7·§10, 결정론).

제N조 / 제N조의M(branch) / ①항 / 1.호 / 가.목 / 부칙(effective_date) / 별표 →
컬럼 매핑·depth·canonical_clause_id·order_seq·parent 계층.
LLM 으로 조번호 생성 금지 — 순수 규칙기반 검증.
"""

from __future__ import annotations

from datetime import date

from app.ingest.clause_parser import parse_clauses


def _by_canonical(clauses):
    return {c.canonical_clause_id: c for c in clauses}


def test_simple_article() -> None:
    """제N조(제목) 본문 → article 매핑·canonical·title."""
    clauses = parse_clauses("제1조(목적) 이 규정은 적용한다.", regulation_id=1)
    assert len(clauses) == 1
    c = clauses[0]
    assert c.depth == "article"
    assert c.article_no == 1
    assert c.article_branch is None
    assert c.clause_label == "제1조"
    assert c.clause_title == "목적"
    assert c.canonical_clause_id == "R1#a1"
    assert c.text == "이 규정은 적용한다."
    assert c.order_seq == 0
    assert c.parent_canonical_id is None


def test_article_branch() -> None:
    """제N조의M → article_branch + canonical 의 '의{branch}' 표기."""
    clauses = parse_clauses("제12조의2(특례) 특례 내용", regulation_id=5)
    c = clauses[0]
    assert c.article_no == 12
    assert c.article_branch == 2
    assert c.clause_label == "제12조의2"
    assert c.canonical_clause_id == "R5#a12의2"


def test_paragraph_circled() -> None:
    """①②(원문자) → paragraph, parent=조, canonical -p{n}."""
    text = "제2조(정의) 용어는 다음과 같다.\n① 첫째 항\n② 둘째 항"
    clauses = parse_clauses(text, regulation_id=1)
    assert len(clauses) == 3
    by = _by_canonical(clauses)
    p1 = by["R1#a2-p1"]
    assert p1.depth == "paragraph"
    assert p1.paragraph_no == 1
    assert p1.clause_label == "①"
    assert p1.text == "첫째 항"
    assert p1.parent_canonical_id == "R1#a2"
    assert by["R1#a2-p2"].paragraph_no == 2
    assert [c.order_seq for c in clauses] == [0, 1, 2]


def test_item_ho_under_article() -> None:
    """호(1. 2.)가 항 없이 조 직속 → parent=조, canonical -i{n}."""
    text = "제3조 본문\n1. 첫째 호\n2. 둘째 호"
    clauses = parse_clauses(text, regulation_id=1)
    by = _by_canonical(clauses)
    i1 = by["R1#a3-i1"]
    assert i1.depth == "item"
    assert i1.item_no == 1
    assert i1.clause_label == "1."
    assert i1.parent_canonical_id == "R1#a3"
    assert by["R1#a3-i2"].item_no == 2


def test_subitem_mok_hierarchy() -> None:
    """가.목 → subitem, 조→항→호→목 4단 계층·canonical 누적."""
    text = "제4조 본문\n① 항 내용\n1. 호 내용\n가. 목 내용\n나. 목 둘"
    clauses = parse_clauses(text, regulation_id=1)
    by = _by_canonical(clauses)
    assert by["R1#a4-p1"].parent_canonical_id == "R1#a4"
    assert by["R1#a4-p1-i1"].parent_canonical_id == "R1#a4-p1"
    sub = by["R1#a4-p1-i1-s가"]
    assert sub.depth == "subitem"
    assert sub.sub_item_label == "가"
    assert sub.clause_label == "가."
    assert sub.parent_canonical_id == "R1#a4-p1-i1"
    assert by["R1#a4-p1-i1-s나"].sub_item_label == "나"


def test_supplementary_effective_date() -> None:
    """부칙 → depth=article, canonical #supp{n}, 시행일 추출."""
    clauses = parse_clauses(
        "부칙 이 규정은 2020년 1월 1일부터 시행한다.", regulation_id=1
    )
    c = clauses[0]
    assert c.depth == "article"
    assert c.clause_label == "부칙"
    assert c.canonical_clause_id == "R1#supp1"
    assert c.effective_date == date(2020, 1, 1)
    assert c.parent_canonical_id is None


def test_multiple_supplementary() -> None:
    """부칙 여러 개 → #supp1, #supp2 순번."""
    text = (
        "부칙 이 규정은 2019. 3. 2.부터 시행한다.\n"
        "부칙 이 개정 규정은 2021. 7. 1.부터 시행한다."
    )
    clauses = parse_clauses(text, regulation_id=9)
    canons = [c.canonical_clause_id for c in clauses]
    assert canons == ["R9#supp1", "R9#supp2"]
    assert clauses[1].effective_date == date(2021, 7, 1)


def test_appendix_as_clause() -> None:
    """별표를 clause 로 적재 시 canonical #appx{n}, depth=article."""
    clauses = parse_clauses("별표1 수당 지급 기준표", regulation_id=1)
    c = clauses[0]
    assert c.canonical_clause_id == "R1#appx1"
    assert c.depth == "article"
    assert c.clause_label == "별표1"


def test_canonical_matches_plan_example() -> None:
    """plan §7 예시: R742#a12의2-p1."""
    text = "제12조의2(특례) 머리\n① 첫째 항"
    clauses = parse_clauses(text, regulation_id=742)
    by = _by_canonical(clauses)
    assert "R742#a12의2-p1" in by
    assert by["R742#a12의2-p1"].paragraph_no == 1


def test_continuation_lines_appended() -> None:
    """마커 없는 후속 줄은 직전 clause 본문에 이어붙임."""
    text = "제1조(목적)\n이 규정은 회사의\n운영 기준을 정한다."
    clauses = parse_clauses(text, regulation_id=1)
    assert len(clauses) == 1
    assert clauses[0].clause_title == "목적"
    assert clauses[0].text == "이 규정은 회사의 운영 기준을 정한다."


def test_article_resets_paragraph_numbering() -> None:
    """새 조 시작 시 항 parent 가 새 조로 갱신(번호 재시작)."""
    text = "제1조 가\n① 항A\n제2조 나\n① 항B"
    clauses = parse_clauses(text, regulation_id=1)
    by = _by_canonical(clauses)
    assert by["R1#a1-p1"].parent_canonical_id == "R1#a1"
    assert by["R1#a2-p1"].parent_canonical_id == "R1#a2"
    assert by["R1#a2-p1"].text == "항B"


def test_order_seq_monotonic() -> None:
    """order_seq 는 문서 출현순 0..N 단조 증가."""
    text = "제1조 가\n① 항\n1. 호\n제2조 나"
    clauses = parse_clauses(text, regulation_id=1)
    assert [c.order_seq for c in clauses] == [0, 1, 2, 3]
