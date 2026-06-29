"""PGroonga 검색 SQL 조립 — 순수 함수, DB 미접속 (plan §4.5).

build_search_sql 은 (sql, params) 만 반환한다. 모든 사용자 입력은 named 파라미터(%(name)s)로만
전달해 SQL injection 을 차단한다(SQL 본문엔 구조만, 값은 params). 조항 직격(clause_ref) 시
btree 정확매칭 CTE 를 FTS 와 UNION ALL 하고 chunk_id 단위 dedup(exact 우선)한다(§4.3).
authority_cell 결정론 인용을 위해 authority_matrix 를 LEFT JOIN 해 canonical_authority_id 를
비정규화한다(§4.5, major-1).
"""

from __future__ import annotations

from datetime import date

# recency 감쇠 반감기(일). 작을수록 최근 글에 가파른 우대. 마감공지처럼 매월 반복되어
# 렉시컬 raw 가 동률인 시계열 공지에서 최신판이 상단으로 오도록 90일로 단축(was 365).
# recency_w=0.0 이면 score=raw_score(가중 비활성).
HALF_LIFE_DAYS: float = 90.0

# SearchHit 매핑 대상 컬럼(am.canonical_authority_id 비정규화 포함). 두 경로 컬럼 정합 유지.
_HIT_COLS = (
    "chunk.chunk_id, chunk.chunk_class, chunk.board_id, chunk.body, "
    "chunk.canonical_clause_id, am.canonical_authority_id, "
    "chunk.clause_label, chunk.source_post_id, chunk.clause_id, "
    "chunk.source_attachment_id, chunk.authority_id, chunk.posted_at, chunk.meta"
)

# 공통 필터(보드·현행·시행일). 모두 파라미터화.
_FILTERS = (
    "(%(boards)s::int[] IS NULL OR chunk.board_id = ANY(%(boards)s)) "
    "AND (NOT %(only_current)s OR chunk.is_current) "
    "AND (%(as_of)s::timestamptz IS NULL OR chunk.posted_at IS NULL "
    "OR chunk.posted_at <= %(as_of)s)"
)

# recency 가중(SQL 산술, LLM 금지). posted_at NULL → 0(보정 없음).
_RECENCY_FACTOR = (
    "COALESCE(1.0 / (1.0 + (EXTRACT(EPOCH FROM (now() - posted_at)) / 86400.0) "
    "/ %(half_life)s), 0.0)"
)


def build_search_sql(
    normalized_query: str,
    *,
    clause_ref: str | None = None,
    board_ids: list[int] | None = None,
    only_current: bool = True,
    as_of: date | None = None,
    limit: int = 30,
    use_synonym_expand: bool = True,
    recency_w: float = 0.0,
) -> tuple[str, dict]:
    """검색 SQL 과 파라미터 dict 를 조립한다(DB 미접속, 순수).

    use_synonym_expand=True 면 본문 매칭에 pgroonga_query_expand 를, False 면 정규화 질의 원문을
    &@~ 에 바인딩한다. clause_ref 가 있으면 btree 정확 경로를 FTS 와 UNION ALL 한다.
    """
    match_expr = (
        "pgroonga_query_expand('glossary_synonym', 'headword', 'synonyms', %(q)s)"
        if use_synonym_expand
        else "%(q)s"
    )

    fts_select = (
        f"SELECT {_HIT_COLS}, "
        f"pgroonga_score(chunk.tableoid, chunk.ctid) AS raw_score, "
        f"'fts'::text AS match_kind "
        f"FROM chunk "
        f"LEFT JOIN authority_matrix am ON am.authority_id = chunk.authority_id "
        f"WHERE ( chunk.body &@~ {match_expr} "
        f"OR (chunk.tokenized IS NOT NULL AND chunk.tokenized &@~ {match_expr}) ) "
        f"AND {_FILTERS}"
    )

    params: dict = {
        "q": normalized_query,
        "boards": board_ids,
        "only_current": only_current,
        "as_of": as_of,
        "recency_w": recency_w,
        "half_life": HALF_LIFE_DAYS,
        "limit": limit,
    }

    if clause_ref is not None:
        params["cid"] = clause_ref
        exact_select = (
            f"SELECT {_HIT_COLS}, "
            f"1.0::real AS raw_score, "
            f"'exact'::text AS match_kind "
            f"FROM chunk "
            f"LEFT JOIN authority_matrix am ON am.authority_id = chunk.authority_id "
            f"WHERE chunk.canonical_clause_id = %(cid)s AND {_FILTERS}"
        )
        union_block = f"{exact_select}\nUNION ALL\n{fts_select}"
    else:
        union_block = fts_select

    sql = (
        "WITH unioned AS (\n"
        f"{union_block}\n"
        "),\n"
        "combined AS (\n"
        "  SELECT DISTINCT ON (chunk_id) *\n"
        "  FROM unioned\n"
        "  ORDER BY chunk_id, (match_kind = 'exact') DESC\n"
        ")\n"
        "SELECT chunk_id, chunk_class, board_id, body,\n"
        f"       raw_score * (1.0 + %(recency_w)s * {_RECENCY_FACTOR}) AS score,\n"
        "       raw_score, canonical_clause_id, canonical_authority_id, clause_label,\n"
        "       source_post_id, clause_id, source_attachment_id, authority_id,\n"
        "       posted_at, meta, match_kind\n"
        "FROM combined\n"
        "ORDER BY (match_kind = 'exact') DESC, score DESC\n"
        "LIMIT %(limit)s"
    )
    return sql, params
