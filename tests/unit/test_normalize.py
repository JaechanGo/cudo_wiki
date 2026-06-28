"""normalize 단위테스트 — 원문자/전각/공백 정규화 + 조항패턴 추출 (DB 불필요)."""

from __future__ import annotations

from app.search.normalize import extract_clause_ref, normalize


def test_circled_number_to_ascii():
    assert normalize("①항") == "1항"


def test_fullwidth_to_halfwidth():
    # 전각 숫자/영문 → 반각
    assert normalize("ＡＢＣ１２３") == "ABC123"


def test_whitespace_collapse_and_strip():
    assert normalize("  제15조   알려줘 ") == "제15조 알려줘"


def test_normalize_idempotent():
    once = normalize("제15조  ①")
    assert normalize(once) == once


def test_extract_clause_ref_korean_article():
    assert extract_clause_ref("제15조 알려줘") == "제15조"


def test_extract_clause_ref_article_with_paragraph():
    assert extract_clause_ref("제15조제2항 내용") == "제15조제2항"


def test_extract_clause_ref_direct_canonical_id():
    # 공백 없는 단일 토큰 + 'N조' 포함 → 직접 canonical id 입력으로 간주(규칙 비의존).
    assert extract_clause_ref("REG-인사-제15조") == "REG-인사-제15조"


def test_extract_clause_ref_none_when_absent():
    assert extract_clause_ref("연차 휴가 며칠") is None
