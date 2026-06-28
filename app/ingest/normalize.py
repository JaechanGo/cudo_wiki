"""한국어 본문 정제·정규화 (plan §7, 결정론).

- ``normalize_circled_digits``: 원문자(①)·전각문자를 반각/아라비아로 정규화(NFKC).
  clause_parser 가 ①②③ 항 번호를 파싱하기 전 선처리로 호출한다.
- ``clean_html``: HTML 태그/엔티티 제거 + EUC-KR↔latin-1 모지바케 복원 + 공백 정규화.
  BizBox 본문(2-hop iframe HTML)을 plain text(body_text)로 변환.

LLM 미사용 — 순수 규칙기반(인용 결정론, NFR).
"""

from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

# 블록 경계 → 줄바꿈(조/항 구조 보존). 인라인 태그(b/span/a)는 단어 연결 유지.
_BLOCK_TAGS = [
    "p", "div", "li", "ul", "ol", "tr", "table", "thead", "tbody",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "blockquote", "pre", "hr",
]

_HANGUL_RE = re.compile(r"[가-힣]")
# 공백류: 일반/탭/개행 외 nbsp( )·전각공백(　) 포함.
_INLINE_WS_RE = re.compile(r"[ \t 　\f\v]+")


def normalize_circled_digits(s: str) -> str:
    """원문자·전각문자를 정규화(NFKC): ①→1, ⑩→10, 전각 １→1, 전각공백→공백.

    NFKC 는 한글 음절(NFC 안정)은 보존하므로 본문 한글을 깨지 않는다.
    """
    if not s:
        return s
    return unicodedata.normalize("NFKC", s)


def _count_hangul(s: str) -> int:
    return len(_HANGUL_RE.findall(s))


def _fix_mojibake(text: str, declared_charset: str | None) -> str:
    """EUC-KR 바이트가 latin-1 로 잘못 디코드된 모지바케를 복원(휴리스틱).

    이미 한글이 있고 치환문자(�)가 없으면 정상으로 보고 그대로 둔다.
    그 외에는 latin-1 로 재인코딩 후 declared_charset → euc-kr → cp949 순으로
    디코드를 시도하여 **한글 수가 가장 많이 늘어나는** 후보를 채택한다.
    """
    if "�" not in text and _count_hangul(text) > 0:
        return text

    encodings: list[str] = []
    if declared_charset:
        encodings.append(declared_charset)
    for enc in ("euc-kr", "cp949", "utf-8"):
        if enc not in encodings:
            encodings.append(enc)

    best = text
    best_score = _count_hangul(text)
    for enc in encodings:
        try:
            recoded = text.encode("latin-1").decode(enc)
        except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
            continue
        score = _count_hangul(recoded)
        if score > best_score:
            best_score = score
            best = recoded
    return best


def _normalize_whitespace(text: str) -> str:
    """줄 내부 공백류는 단일 공백으로, 빈 줄 제거, 줄은 개행으로 연결."""
    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = _INLINE_WS_RE.sub(" ", raw_line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def clean_html(html: str, declared_charset: str | None) -> str:
    """HTML → plain text. 모지바케 복원 → 태그/엔티티 제거 → 공백 정규화.

    Args:
        html: 원본 HTML(혹은 모지바케 문자열).
        declared_charset: 응답이 선언한 charset(있으면 모지바케 복원에 우선 사용).

    Returns:
        정제된 plain text(블록 경계는 개행으로 보존).
    """
    if not html:
        return ""

    fixed = _fix_mojibake(html, declared_charset)
    soup = BeautifulSoup(fixed, "lxml")

    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")

    return _normalize_whitespace(soup.get_text())
