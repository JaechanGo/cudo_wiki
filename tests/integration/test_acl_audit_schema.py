"""0004 acl_audit 마이그레이션 회귀 (@integration — DB 필요, 없으면 skip).

13→14표 카운트 + acl_audit 컬럼/CHECK enum 검증(test_schema.py/test_enum_check_regression.py 패턴).
"""

from __future__ import annotations

import psycopg
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def conn(migrated_db):
    with psycopg.connect(migrated_db["libpq"]) as c:
        yield c


def test_acl_audit_table_exists(conn):
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='acl_audit'"
    ).fetchone()
    assert row is not None, "acl_audit 테이블 부재(0004 미적용)"


def test_fourteen_tables(conn):
    """0002 13표 + 0004 acl_audit = 14표(상위집합 검증, subset 패턴)."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE'"
    ).fetchall()
    names = {r[0] for r in rows}
    expected = {
        "board", "post", "regulation", "clause", "chunk", "attachment",
        "attachment_page", "authority_matrix", "glossary_synonym", "ingest_state",
        "eval_query", "eval_gold", "query_log", "acl_audit",
    }
    assert expected <= names, f"누락 테이블: {expected - names}"


def test_acl_audit_columns(conn):
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='acl_audit'"
    ).fetchall()
    cols = {r[0] for r in rows}
    expected = {
        "acl_audit_id", "occurred_at", "tool_name", "user_role", "user_email_hash",
        "identity_present", "decision", "requested_board_ids", "allowed_board_ids",
        "denied_board_ids", "reason", "session_id",
    }
    assert expected <= cols, f"누락 컬럼: {expected - cols}"


def test_acl_audit_decision_check_enum(conn):
    """decision CHECK enum — 0002 enum-CHECK 스타일과 일관."""
    defs = conn.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='acl_audit'::regclass AND contype='c'"
    ).fetchall()
    joined = " ".join(d[0] for d in defs)
    for value in ("allow", "deny", "identity_absent", "filtered"):
        assert value in joined, f"decision CHECK 에 {value} 누락"


def test_acl_audit_decision_rejects_invalid(conn):
    """잘못된 decision 값 → CHECK 위반(독립 트랜잭션 롤백)."""
    with conn.transaction(force_rollback=True):
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO acl_audit (tool_name, identity_present, decision) "
                "VALUES ('search_regulations', false, 'INVALID')"
            )


def test_acl_audit_insert_minimal(conn):
    """필수 컬럼만으로 insert 성공(occurred_at 기본값)."""
    with conn.transaction(force_rollback=True):
        row = conn.execute(
            "INSERT INTO acl_audit (tool_name, identity_present, decision) "
            "VALUES ('list_boards', true, 'allow') RETURNING acl_audit_id, occurred_at"
        ).fetchone()
        assert row[0] is not None
        assert row[1] is not None


def test_acl_audit_indexes(conn):
    defs = {
        r[0]
        for r in conn.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname='public' AND tablename='acl_audit'"
        ).fetchall()
    }
    assert "idx_acl_audit_occurred_at" in defs
    assert "idx_acl_audit_decision" in defs
