"""한국어 질의 정규화 + 조항 패턴 추출 — 순수 함수 (plan §2, §4.3).

normalize 는 NFKC(원문자 ①→1·전각→반각) + 공백 정리. extract_clause_ref 는 조항 직격
경로(btree canonical_clause_id 정확매칭)용 참조 토큰을 추출한다 — canonical 명명규칙(R-1)에
비의존하며 문자열만 다룬다.
"""

from __future__ import annotations

import re
import unicodedata

# 한국어 조항 패턴: "제15조", "제15조제2항", "15조2항"(제 생략) 등.
_ARTICLE_RE = re.compile(
    r"제?\s*(\d+)\s*조"
    r"(?:\s*(?:의\s*(\d+))?)?"          # 조의N (가지번호)
    r"(?:\s*제?\s*(\d+)\s*항)?"
    r"(?:\s*제?\s*(\d+)\s*호)?"
)

# 직접 canonical id 입력 판별: 공백 없는 단일 토큰이며 'N조'(숫자+조)를 포함.
_CANONICAL_TOKEN_RE = re.compile(r"^\S*\d+조\S*$")


def normalize(text: str) -> str:
    """질의를 NFKC 정규화(원문자·전각 → 표준) 후 연속 공백을 1개로 줄이고 trim 한다."""
    nfkc = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", nfkc).strip()


def extract_clause_ref(text: str) -> str | None:
    """질의에서 조항 직격 참조를 추출한다(없으면 None).

    1) 공백 없는 단일 토큰이고 'N조'를 포함하면 직접 canonical id 입력으로 보고 그대로 반환.
    2) 아니면 한국어 조항 패턴(제N조[의M][제K항][제L호])을 정규형으로 조립해 반환.
    문자열 동등비교 전용이며 canonical 명명규칙에는 의존하지 않는다(R-1).
    """
    norm = normalize(text)
    if not norm:
        return None

    if " " not in norm and _CANONICAL_TOKEN_RE.match(norm):
        return norm

    m = _ARTICLE_RE.search(norm)
    if not m:
        return None
    article, branch, paragraph, item = m.groups()
    ref = f"제{int(article)}조"
    if branch:
        ref += f"의{int(branch)}"
    if paragraph:
        ref += f"제{int(paragraph)}항"
    if item:
        ref += f"제{int(item)}호"
    return ref
