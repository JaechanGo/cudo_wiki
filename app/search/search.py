"""PGroonga 렉시컬 검색 — query_builder 실행 + 행→SearchHit 매핑 (plan §4, read-only).

conn 은 psycopg AsyncConnection. 행→dataclass 매핑은 dict_row 키 기반(컬럼 多·frozen, minor-4).
빈 질의는 graceful 빈 결과(예외 아님). DB 오류는 호출자(C)로 전파(B 가 삼키지 않음).
"""

from __future__ import annotations

from datetime import date

from psycopg.rows import dict_row

from app.common.config import get_settings
from app.search.normalize import extract_clause_ref, normalize
from app.search.query_builder import build_search_sql
from app.search.types import SearchHit, SearchResult


def _row_to_hit(row: dict) -> SearchHit:
    """dict_row 행을 SearchHit 으로 매핑(match_kind 등 부가 컬럼은 무시)."""
    return SearchHit(
        chunk_id=row["chunk_id"],
        chunk_class=row["chunk_class"],
        board_id=row["board_id"],
        body=row["body"],
        score=float(row["score"]),
        raw_score=float(row["raw_score"]),
        canonical_clause_id=row["canonical_clause_id"],
        canonical_authority_id=row["canonical_authority_id"],
        clause_label=row["clause_label"],
        source_post_id=row["source_post_id"],
        clause_id=row["clause_id"],
        source_attachment_id=row["source_attachment_id"],
        authority_id=row["authority_id"],
        posted_at=row["posted_at"],
        meta=row["meta"],
    )


async def search(
    conn,
    query: str,
    *,
    board_ids: list[int] | None = None,
    only_current: bool = True,
    as_of: date | None = None,
    limit: int = 30,
    use_synonym_expand: bool = True,
    use_mecab_parallel: bool | None = None,  # R0: 단일 OR(body|tokenized) — 보드 분기 불필요(D-02)
    recency_w: float | None = None,
) -> SearchResult:
    """질의를 정규화·확장해 PGroonga 로 후보 top-N 을 조회한다.

    조항 직격 참조가 추출되면 btree 정확 경로를 우선(strategy="exact_clause").
    board_ids 는 ACL 사전결정 결과를 받는 파라미터(필터 주체는 C). 빈 질의는 빈 결과.
    recency_w=None 이면 설정값(search_recency_w)을 사용 — 현행 결과 안에서도 최신 글 우선.
    """
    if recency_w is None:
        recency_w = get_settings().search_recency_w
    normalized = normalize(query)
    if not normalized:
        return SearchResult(
            query=query, normalized_query="", strategy="ngram",
            expanded_query="", hits=[], top_score=0.0,
        )

    clause_ref = extract_clause_ref(normalized)

    def _sql(match_query: str):
        return build_search_sql(
            match_query,
            clause_ref=clause_ref,
            board_ids=board_ids,
            only_current=only_current,
            as_of=as_of,
            limit=limit,
            use_synonym_expand=use_synonym_expand,
            recency_w=recency_w,
        )

    async with conn.cursor(row_factory=dict_row) as cur:
        if use_synonym_expand:
            await cur.execute(
                "SELECT pgroonga_query_expand("
                "'glossary_synonym', 'headword', 'synonyms', %s) AS eq",
                (normalized,),
            )
            expanded_query = (await cur.fetchone())["eq"]
        else:
            expanded_query = normalized

        # 1차: PGroonga &@~ 는 공백을 AND 로 본다(정밀). 모든 토큰을 포함한 chunk 만 매칭.
        sql, params = _sql(normalized)
        await cur.execute(sql, params)
        rows = await cur.fetchall()

        # OR 폴백: 다토큰 질의의 AND 결과가 빈약하면(< MIN_AND_HITS) 토큰 OR 로 재검색해 recall 확보.
        # OR 은 AND 의 superset 이므로 기존 매칭을 잃지 않고, recency 가중이 최신을 상단으로 끌어올린다
        # (예: "6월 개인경비 마감일" → '마감일' 토큰이 최신 마감공지 본문엔 없어 AND 3건[옛글]뿐 →
        #  OR 로 '6월/개인경비/마감일' 매칭 → 최신 마감공지 포함). AND 가 충분하면 폴백 안 함(정밀 보존).
        # 정밀도 하락은 후단 GLM 리랭크 + 거절 게이트가 흡수. 조항 직격(exact)은 제외.
        MIN_AND_HITS = 5
        or_fallback = False
        tokens = normalized.split()
        if len(rows) < MIN_AND_HITS and clause_ref is None and len(tokens) > 1:
            sql, params = _sql(" OR ".join(tokens))
            await cur.execute(sql, params)
            or_rows = await cur.fetchall()
            if len(or_rows) > len(rows):  # OR 이 더 많이 회수했을 때만 교체.
                rows = or_rows
                or_fallback = True

    hits = [_row_to_hit(r) for r in rows]
    is_exact = any(r.get("match_kind") == "exact" for r in rows)
    if is_exact:
        strategy = "exact_clause"
    elif or_fallback:
        strategy = "or_fallback"
    elif use_synonym_expand:
        strategy = "synonym_expanded"
    else:
        strategy = "ngram"

    top_score = hits[0].score if hits else 0.0
    return SearchResult(
        query=query,
        normalized_query=normalized,
        strategy=strategy,
        expanded_query=expanded_query,
        hits=hits,
        top_score=top_score,
    )
