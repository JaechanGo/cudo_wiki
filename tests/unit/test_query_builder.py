"""build_search_sql 단위테스트 — SQL/파라미터 문자열 단언 (DB 미접속, plan §9.1)."""

from __future__ import annotations

from datetime import date

from app.search.query_builder import HALF_LIFE_DAYS, build_search_sql


def test_basic_expand_sql_and_params():
    sql, params = build_search_sql("연차")
    assert "pgroonga_query_expand('glossary_synonym', 'headword', 'synonyms', %(q)s)" in sql
    assert "&@~" in sql
    assert "LEFT JOIN authority_matrix am ON am.authority_id = chunk.authority_id" in sql
    assert "am.canonical_authority_id" in sql
    assert "ORDER BY" in sql
    assert "LIMIT %(limit)s" in sql
    assert params["q"] == "연차"
    assert params["only_current"] is True
    assert params["limit"] == 30
    assert params["boards"] is None
    assert params["recency_w"] == 0.0
    assert params["half_life"] == HALF_LIFE_DAYS
    assert "cid" not in params


def test_no_synonym_expand_uses_raw_query():
    sql, params = build_search_sql("연차", use_synonym_expand=False)
    assert "pgroonga_query_expand" not in sql
    assert "chunk.body &@~ %(q)s" in sql
    assert params["q"] == "연차"


def test_exact_clause_union_path():
    sql, params = build_search_sql("REG-인사-제15조", clause_ref="REG-인사-제15조")
    assert "chunk.canonical_clause_id = %(cid)s" in sql
    assert "UNION ALL" in sql
    assert params["cid"] == "REG-인사-제15조"
    # exact 경로는 pgroonga_score 미사용 → 상수 신뢰도.
    assert "1.0::real AS raw_score" in sql


def test_board_and_asof_filters():
    sql, params = build_search_sql(
        "연차", board_ids=[1, 2], as_of=date(2025, 1, 1), only_current=False, limit=10
    )
    assert "chunk.board_id = ANY(%(boards)s)" in sql
    assert "%(as_of)s::timestamptz" in sql
    assert params["boards"] == [1, 2]
    assert params["as_of"] == date(2025, 1, 1)
    assert params["only_current"] is False
    assert params["limit"] == 10


def test_injection_safe_user_text_only_in_params():
    evil = "'; DROP TABLE chunk; --"
    sql, params = build_search_sql(evil)
    assert evil not in sql           # 사용자 입력은 SQL 본문에 박히지 않음
    assert params["q"] == evil       # 파라미터로만 전달
