"""조항 파싱 — 결정론 1급 (plan §7). LLM 절대 금지, 순수 규칙기반.

규정 본문 텍스트를 줄 단위로 스캔하여 조/항/호/목/부칙/별표를 clause 행으로 매핑한다.
조번호·항·호는 **파서가 생성**(인용 결정론, NFR 인용정확도 ≥98%).

canonical_clause_id 포맷(plan §7, key=R{regulation_id}):
  조      R{rid}#a{article}[의{branch}]
  항      …조canonical-p{para}
  호      …상위canonical-i{item}
  목      …상위canonical-s{label}      (※ subitem 유일성 보장용 확장 — plan 포맷의 자연 연장)
  부칙    R{rid}#supp{n}               (n = 부칙 출현 순서)
  별표    R{rid}#appx{n}               (clause 로 적재되는 별표만)

depth CHECK enum = {article, paragraph, item, subitem} → 부칙/별표는 top-level 'article'.
"""

from __future__ import annotations

import re
from datetime import date

from app.ingest.models import ParsedClause
from app.ingest.normalize import normalize_circled_digits

# ── 마커 정규식 (모두 줄 시작 anchor) ─────────────────────────────────────────
_ARTICLE_RE = re.compile(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
_SUPP_RE = re.compile(r"^부\s*칙")
_APPENDIX_RE = re.compile(r"^별\s*[표지]\s*(\d+)?")
# 원문자 항: ①-⑳(2460-2473), ㉑-㉟(3251-325f), ㊱-㊿(32b1-32bf).
_PARA_RE = re.compile(r"^([①-⑳㉑-㉟㊱-㊿])")
_ITEM_RE = re.compile(r"^(\d+)\s*\.")
# 목 마커: 표준 한글 enumeration 14자 + '.' (문장 오탐 최소화).
_MOK_RE = re.compile(r"^([가나다라마바사아자차카타파하])\s*\.")
_TITLE_RE = re.compile(r"\(([^)]*)\)\s*(.*)$")
_DATE_RE = re.compile(r"(\d{4})\s*[.년]\s*(\d{1,2})\s*[.월]\s*(\d{1,2})")


def _split_title(rest: str) -> tuple[str | None, str]:
    """조 머리 뒤 ``(제목) 본문`` → (제목, 본문). 괄호 없으면 (None, 전체)."""
    if rest.startswith("("):
        m = _TITLE_RE.match(rest)
        if m:
            return (m.group(1).strip() or None), m.group(2).strip()
    return None, rest


def _extract_date(text: str) -> date | None:
    """부칙 시행일: ``YYYY년 M월 D일`` / ``YYYY. M. D`` 첫 매칭 → date."""
    m = _DATE_RE.search(text)
    if not m:
        return None
    year, month, day = (int(g) for g in m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_clauses(reg_text: str, regulation_id: int) -> list[ParsedClause]:
    """규정 본문 → ParsedClause 목록(결정론). order_seq=문서 출현순 0..N.

    Args:
        reg_text: 정제된 규정 본문(clean_html 산출 권장).
        regulation_id: §4 멱등 보존된 regulation_id → canonical key ``R{rid}``.

    Returns:
        문서 출현순 ParsedClause 리스트.
    """
    key = f"R{regulation_id}"
    rows: list[dict] = []
    order = 0
    cur_article: dict | None = None
    cur_para: dict | None = None
    cur_item: dict | None = None
    last: dict | None = None
    supp_n = 0
    appx_n = 0

    def emit(**kw: object) -> dict:
        nonlocal order, last
        kw["order_seq"] = order
        order += 1
        rows.append(kw)
        last = kw
        return kw

    for raw in reg_text.splitlines():
        line = raw.strip()
        if not line:
            continue

        m = _ARTICLE_RE.match(line)
        if m:
            art = int(m.group(1))
            branch = int(m.group(2)) if m.group(2) else None
            title, text = _split_title(line[m.end():].strip())
            canonical = f"{key}#a{art}" + (f"의{branch}" if branch else "")
            label = f"제{art}조" + (f"의{branch}" if branch else "")
            cur_article = emit(
                canonical_clause_id=canonical, clause_label=label, text=text,
                depth="article", article_no=art, article_branch=branch,
                clause_title=title, parent_canonical_id=None,
            )
            cur_para = cur_item = None
            continue

        m = _SUPP_RE.match(line)
        if m:
            supp_n += 1
            rest = line[m.end():].strip()
            cur_article = emit(
                canonical_clause_id=f"{key}#supp{supp_n}", clause_label="부칙",
                text=rest, depth="article", effective_date=_extract_date(line),
                parent_canonical_id=None,
            )
            cur_para = cur_item = None
            continue

        m = _APPENDIX_RE.match(line)
        if m:
            appx_n += 1
            num = m.group(1) or ""
            rest = line[m.end():].strip()
            cur_article = emit(
                canonical_clause_id=f"{key}#appx{appx_n}",
                clause_label=f"별표{num}", text=rest, depth="article",
                parent_canonical_id=None,
            )
            cur_para = cur_item = None
            continue

        m = _PARA_RE.match(line)
        if m:
            para = int(normalize_circled_digits(m.group(1)))
            rest = line[m.end():].strip()
            parent = cur_article["canonical_clause_id"] if cur_article else f"{key}#a0"
            cur_para = emit(
                canonical_clause_id=f"{parent}-p{para}", clause_label=m.group(1),
                text=rest, depth="paragraph", paragraph_no=para,
                parent_canonical_id=parent,
            )
            cur_item = None
            continue

        m = _ITEM_RE.match(line)
        if m:
            item = int(m.group(1))
            rest = line[m.end():].strip()
            owner = cur_para or cur_article
            parent = owner["canonical_clause_id"] if owner else f"{key}#a0"
            cur_item = emit(
                canonical_clause_id=f"{parent}-i{item}", clause_label=f"{item}.",
                text=rest, depth="item", item_no=item, parent_canonical_id=parent,
            )
            continue

        m = _MOK_RE.match(line)
        if m:
            sub = m.group(1)
            rest = line[m.end():].strip()
            owner = cur_item or cur_para or cur_article
            parent = owner["canonical_clause_id"] if owner else f"{key}#a0"
            emit(
                canonical_clause_id=f"{parent}-s{sub}", clause_label=f"{sub}.",
                text=rest, depth="subitem", sub_item_label=sub,
                parent_canonical_id=parent,
            )
            continue

        # 마커 없는 줄 → 직전 clause 본문에 이어붙임(continuation).
        if last is not None:
            prev = last.get("text") or ""
            last["text"] = f"{prev} {line}".strip()

    return [_to_parsed(r) for r in rows]


def _to_parsed(r: dict) -> ParsedClause:
    return ParsedClause(
        canonical_clause_id=r["canonical_clause_id"],
        clause_label=r["clause_label"],
        text=r.get("text") or "",
        depth=r["depth"],
        order_seq=r["order_seq"],
        article_no=r.get("article_no"),
        article_branch=r.get("article_branch"),
        paragraph_no=r.get("paragraph_no"),
        item_no=r.get("item_no"),
        sub_item_label=r.get("sub_item_label"),
        clause_title=r.get("clause_title"),
        effective_date=r.get("effective_date"),
        parent_canonical_id=r.get("parent_canonical_id"),
    )
