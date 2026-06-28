"""PGroonga 렉시컬 검색 — query_builder 실행 + 행→SearchHit 매핑 (plan §4, read-only).

conn 은 psycopg AsyncConnection. 행→dataclass 매핑은 dict_row 키 기반(컬럼 多·frozen, minor-4).
빈 질의는 graceful 빈 결과(예외 아님). DB 오류는 호출자(C)로 전파(B 가 삼키지 않음).
"""

from __future__ import annotations

from datetime import date

from psycopg.rows import dict_row

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
) -> SearchResult:
    """질의를 정규화·확장해 PGroonga 로 후보 top-N 을 조회한다.

    조항 직격 참조가 추출되면 btree 정확 경로를 우선(strategy="exact_clause").
    board_ids 는 ACL 사전결정 결과를 받는 파라미터(필터 주체는 C). 빈 질의는 빈 결과.
    """
    normalized = normalize(query)
    if not normalized:
        return SearchResult(
            query=query, normalized_query="", strategy="ngram",
            expanded_query="", hits=[], top_score=0.0,
        )

    clause_ref = extract_clause_ref(normalized)
    sql, params = build_search_sql(
        normalized,
        clause_ref=clause_ref,
        board_ids=board_ids,
        only_current=only_current,
        as_of=as_of,
        limit=limit,
        use_synonym_expand=use_synonym_expand,
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

        await cur.execute(sql, params)
        rows = await cur.fetchall()

    hits = [_row_to_hit(r) for r in rows]
    is_exact = any(r.get("match_kind") == "exact" for r in rows)
    if is_exact:
        strategy = "exact_clause"
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
