"""normalize 단위테스트 (DB 불필요).

두 서브시스템의 정규화 모듈을 한 파일에서 검증(rebase 병합 — 서로 다른 모듈):
  · 검색 코어 B  : ``app.search.normalize``  (질의 정규화 + 조항패턴 추출)  — Task 008
  · 인제스트  A  : ``app.ingest.normalize`` (원문자/HTML/모지바케 정제)    — Task 007
함수명이 겹치지 않아 한 모듈에 공존 가능.
"""

from __future__ import annotations

from app.ingest.normalize import clean_html, normalize_circled_digits
from app.search.normalize import extract_clause_ref, normalize

# ════════════════════════════════════════════════════════════════════════════
# 검색 코어 B — app.search.normalize (Task 008)
# ════════════════════════════════════════════════════════════════════════════


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


# ════════════════════════════════════════════════════════════════════════════
# 인제스트 A — app.ingest.normalize (Task 007, plan §10)
#   원문자①→1, 전각숫자→반각, EUC-KR 모지바케 복원, HTML 태그/엔티티 제거, 공백 정규화.
# ════════════════════════════════════════════════════════════════════════════

# ── normalize_circled_digits ────────────────────────────────────────────────


def test_circled_digits_to_arabic() -> None:
    """원문자 ①②③ → 1 2 3 (clause_parser 항 파싱 선처리)."""
    assert normalize_circled_digits("①②③") == "123"


def test_circled_two_digit() -> None:
    """두 자리 원문자 ⑩⑳ → 10 20."""
    assert normalize_circled_digits("⑩") == "10"
    assert normalize_circled_digits("⑳") == "20"


def test_fullwidth_digits_to_halfwidth() -> None:
    """전각 숫자 １２３ → 반각 123."""
    assert normalize_circled_digits("１２３") == "123"


def test_circled_in_context() -> None:
    """문맥 속 원문자만 치환, 한글/숫자 보존."""
    assert normalize_circled_digits("제1조 ①목적") == "제1조 1목적"


def test_ascii_unchanged() -> None:
    """순수 ASCII 는 변형 없음."""
    assert normalize_circled_digits("abc 123") == "abc 123"


# ── clean_html ──────────────────────────────────────────────────────────────


def test_clean_html_strips_tags() -> None:
    """태그 제거, 인라인 태그 경계에서 단어가 깨지지 않음."""
    assert clean_html("<p>제1조 <b>목적</b></p>", None) == "제1조 목적"


def test_clean_html_unescapes_entities() -> None:
    """HTML 엔티티 해제 (&amp; → &, &lt; → <)."""
    assert clean_html("<p>A &amp; B &lt;tag&gt;</p>", None) == "A & B <tag>"


def test_clean_html_drops_script_style() -> None:
    """script/style 내용은 본문에서 제외."""
    assert clean_html("<div>본문<script>alert(1)</script></div>", None) == "본문"


def test_clean_html_block_tags_to_newline() -> None:
    """블록 경계(<p>)는 줄바꿈으로 분리 → 조항 파서 입력 구조 보존."""
    assert clean_html("<p>제1조</p><p>제2조</p>", None) == "제1조\n제2조"


def test_clean_html_empty() -> None:
    """빈 입력 → 빈 문자열."""
    assert clean_html("", None) == ""


def test_clean_html_keeps_clean_korean() -> None:
    """정상 UTF-8 한글은 그대로(이중 복원 방지)."""
    assert clean_html("정상 한글", None) == "정상 한글"


def test_clean_html_collapses_whitespace() -> None:
    """연속 공백/전각공백/nbsp 를 단일 공백으로 정규화."""
    assert clean_html("<p>제1조　   목적</p>", None) == "제1조 목적"


def test_clean_html_euckr_mojibake_with_declared_charset() -> None:
    """EUC-KR 바이트를 latin-1 로 잘못 디코드한 모지바케를 declared_charset 으로 복원."""
    original = "제1조(목적) 이 규정은 적용한다"
    mojibake = original.encode("euc-kr").decode("latin-1")
    assert clean_html(mojibake, "euc-kr") == original


def test_clean_html_euckr_mojibake_heuristic_no_charset() -> None:
    """declared_charset 부재 시에도 휴리스틱(euc-kr/cp949)으로 모지바케 복원."""
    original = "제2조 임직원의 책임"
    mojibake = original.encode("euc-kr").decode("latin-1")
    assert clean_html(mojibake, None) == original
