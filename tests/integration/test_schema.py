"""스키마 introspection 통합테스트 (@integration — DB 필요, 없으면 skip).

`alembic upgrade head` 후 실제 DB 를 information_schema/pg_catalog 로 검증.

[m-1 deviation 라벨] 13표 모두 생성 / embedding 1컬럼만 phase-2 이연 = 의도된 R0
deviation(ADR-002). 전체 195컬럼 = erd 196 − embedding 1. → 결함 아님.
(test_embedding_absent / test_total_column_count 가 이 라벨의 회귀 가드.)
"""

from __future__ import annotations

import psycopg
import pytest

pytestmark = pytest.mark.integration

# erd.json 13표.
EXPECTED_TABLES = {
    "board", "post", "regulation", "clause", "chunk", "attachment",
    "attachment_page", "authority_matrix", "glossary_synonym", "ingest_state",
    "eval_query", "eval_gold", "query_log",
}

# erd 컬럼 합계 196 − embedding 1(phase-2) = 195.
EXPECTED_TOTAL_COLUMNS = 195


@pytest.fixture
def conn(migrated_db):
    with psycopg.connect(migrated_db["libpq"]) as c:
        yield c


def test_thirteen_tables(conn):
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE'"
    ).fetchall()
    names = {r[0] for r in rows}
    assert EXPECTED_TABLES <= names, f"누락 테이블: {EXPECTED_TABLES - names}"


def test_total_column_count(conn):
    """[m-1] 13표 전체 컬럼 = 195 (= erd 196 − embedding). 스키마 충실도 회귀 가드."""
    placeholders = ",".join(["%s"] * len(EXPECTED_TABLES))
    row = conn.execute(
        f"SELECT count(*) FROM information_schema.columns "
        f"WHERE table_schema='public' AND table_name IN ({placeholders})",
        tuple(EXPECTED_TABLES),
    ).fetchone()
    assert row[0] == EXPECTED_TOTAL_COLUMNS, f"컬럼 합계 {row[0]} != {EXPECTED_TOTAL_COLUMNS}"


def test_pgroonga_extension(conn):
    row = conn.execute(
        "SELECT 1 FROM pg_extension WHERE extname='pgroonga'"
    ).fetchone()
    assert row is not None, "pgroonga 확장 미설치"


def test_key_indexes_exist(conn):
    rows = conn.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname='public'"
    ).fetchall()
    names = {r[0] for r in rows}
    required = {
        "idx_chunk_body_pgroonga",
        "idx_chunk_tokenized_pgroonga",
        "idx_post_title_pgroonga",
        "idx_post_body_text_pgroonga",
        "idx_clause_canonical_clause_id",
        "idx_authority_amount_band_gist",
        "idx_glossary_headword_pgroonga",
        "idx_glossary_synonyms_pgroonga",
    }
    assert required <= names, f"누락 인덱스: {required - names}"


def test_index_access_methods(conn):
    """핵심 인덱스의 접근 방식(pgroonga / gist) 확인."""
    defs = dict(
        conn.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public'"
        ).fetchall()
    )
    assert "USING pgroonga" in defs["idx_chunk_body_pgroonga"]
    assert "USING pgroonga" in defs["idx_chunk_tokenized_pgroonga"]
    assert "USING gist" in defs["idx_authority_amount_band_gist"]


def test_partial_unique_indexes(conn):
    """부분 unique 3종 (WHERE is_current)."""
    defs = dict(
        conn.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public'"
        ).fetchall()
    )
    for name in (
        "uq_clause_canonical_current",
        "uq_authority_canonical_current",
        "uq_regulation_reg_code_current",
    ):
        assert name in defs, f"부분 unique 인덱스 누락: {name}"
        assert "UNIQUE INDEX" in defs[name].upper()
        assert "is_current" in defs[name]


def test_amount_band_generated_column(conn):
    """authority_matrix.amount_band = 생성열(ALWAYS)."""
    row = conn.execute(
        "SELECT is_generated FROM information_schema.columns "
        "WHERE table_name='authority_matrix' AND column_name='amount_band'"
    ).fetchone()
    assert row is not None, "amount_band 컬럼 부재"
    assert row[0] == "ALWAYS", f"amount_band is_generated={row[0]} (생성열 아님)"


def test_embedding_absent(conn):
    """[m-1] chunk.embedding 부재 (phase-2 이연, ADR-002). 의도된 R0 deviation 회귀 가드."""
    row = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='chunk' AND column_name='embedding'"
    ).fetchone()
    assert row is None, "chunk.embedding 이 R0 에 존재하면 안 됨 (phase-2 이연)"


def test_representative_check_constraint(conn):
    """대표 CHECK enum 존재 — board.board_class 의 'notice' 포함 정의."""
    defs = conn.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='board'::regclass AND contype='c'"
    ).fetchall()
    joined = " ".join(d[0] for d in defs)
    assert "notice" in joined and "regulation" in joined, "board_class CHECK enum 부재"


def test_amount_band_range_query(conn):
    """생성열 int8range 포함질의(@>) 동작 스모크 — 별도 트랜잭션(쓰기 롤백)."""
    with conn.transaction(force_rollback=True):
        bid = conn.execute(
            "INSERT INTO board (bizbox_board_no,name,slug,board_class,default_chunk_strategy) "
            "VALUES (9001,'전결','auth-smoke','authority','authority_cell') RETURNING board_id"
        ).fetchone()[0]
        rid = conn.execute(
            "INSERT INTO regulation (board_id,title,reg_type) "
            "VALUES (%s,'전결규정','전결규정') RETURNING regulation_id",
            (bid,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO authority_matrix "
            "(regulation_id,canonical_authority_id,business_item,action_type,"
            "amount_min,amount_max) "
            "VALUES (%s,'AUTH#1','구매','전결',1000000,5000000)",
            (rid,),
        )
        # 300만원이 [100만,500만] 밴드에 포함.
        hit = conn.execute(
            "SELECT count(*) FROM authority_matrix WHERE amount_band @> %s::int8",
            (3_000_000,),
        ).fetchone()[0]
        assert hit == 1


def test_query_expand_and_fts_smoke(conn):
    """pgroonga_query_expand 호출 + chunk.body &@~ 질의 스모크 (쓰기 롤백)."""
    with conn.transaction(force_rollback=True):
        conn.execute(
            "INSERT INTO glossary_synonym (headword,synonyms,register) "
            "VALUES ('연차', ARRAY['연차','연차휴가','annual leave'], 'official')"
        )
        expanded = conn.execute(
            "SELECT pgroonga_query_expand('glossary_synonym','headword','synonyms','연차')"
        ).fetchone()[0]
        assert "연차" in expanded

        bid = conn.execute(
            "INSERT INTO board (bizbox_board_no,name,slug,board_class,default_chunk_strategy) "
            "VALUES (9002,'공지','notice-smoke','notice','whole') RETURNING board_id"
        ).fetchone()[0]
        pid = conn.execute(
            "INSERT INTO post (board_id,bizbox_art_no,title,doc_type) "
            "VALUES (%s,1,'연차 사용 안내','notice') RETURNING post_id",
            (bid,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO chunk (chunk_class,board_id,source_post_id,seq_in_source,body) "
            "VALUES ('notice_section',%s,%s,0,'연차휴가는 연 15일 부여된다')",
            (bid, pid),
        )
        hit = conn.execute(
            "SELECT count(*) FROM chunk WHERE body &@~ %s", ("연차",)
        ).fetchone()[0]
        assert hit == 1


def test_chunk_source_check_rejects_invalid(conn):
    """택1 CHECK: chunk_class=clause 인데 원천 FK 없으면 거부."""
    with conn.transaction(force_rollback=True):
        bid = conn.execute(
            "INSERT INTO board (bizbox_board_no,name,slug,board_class,default_chunk_strategy) "
            "VALUES (9003,'규정','reg-smoke','regulation','article') RETURNING board_id"
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO chunk (chunk_class,board_id,seq_in_source,body) "
                "VALUES ('clause',%s,0,'본문')",
                (bid,),
            )
