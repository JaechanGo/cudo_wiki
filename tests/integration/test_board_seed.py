"""board_seed 시드 + upsert_board_seed 멱등 (plan §1·§4, DESIGN §7).

- 19보드 시드 / 제외 4보드 부재 → 순수 데이터 단언(DB 불필요).
- 재시드 멱등(행수 불변) + bizbox_board_no→board_id 매핑 / ingest_state 동반 → @integration.
"""

from __future__ import annotations

import psycopg
import pytest

from app.ingest.board_seed import BOARDS

# 제외 보드(개인정보 4개, DESIGN §7).
EXCLUDED_BOARD_NOS = {1401000141, 501000075, 1401000440, 1401000711}


def test_nineteen_boards_no_excluded() -> None:
    """19보드 시드 + 제외 4보드 포함 금지(순수 상수 검증)."""
    assert len(BOARDS) == 19, f"보드 수 {len(BOARDS)} != 19"
    nos = {b.bizbox_board_no for b in BOARDS}
    assert len(nos) == 19, "bizbox_board_no 중복"
    assert nos & EXCLUDED_BOARD_NOS == set(), "제외 보드가 시드에 포함됨"
    slugs = {b.slug for b in BOARDS}
    assert len(slugs) == 19, "slug 중복(UNIQUE 위반 위험)"


def test_regulation_board_present() -> None:
    """사내규정(1401000286)=regulation·article·mecab 병렬."""
    reg = next(b for b in BOARDS if b.bizbox_board_no == 1401000286)
    assert reg.board_class == "regulation"
    assert reg.default_chunk_strategy == "article"
    assert reg.use_mecab_parallel is True


@pytest.fixture
def conn(migrated_db):
    with psycopg.connect(migrated_db["libpq"]) as c:
        yield c


@pytest.mark.integration
def test_seed_creates_19_and_idempotent(conn) -> None:
    """2회 시드 → board 19행 불변, ingest_state 동반, board_id 매핑 안정."""
    from app.ingest.loader import upsert_board_seed

    with conn.transaction(force_rollback=True):
        m1 = upsert_board_seed(conn, BOARDS)
        assert set(m1.keys()) == {b.bizbox_board_no for b in BOARDS}
        n_board = conn.execute("SELECT count(*) FROM board").fetchone()[0]
        assert n_board == 19
        n_state = conn.execute("SELECT count(*) FROM ingest_state").fetchone()[0]
        assert n_state == 19, "보드별 ingest_state 동반 시드 누락"

        # 재시드 → 행수 불변 + board_id 동일성.
        m2 = upsert_board_seed(conn, BOARDS)
        assert m2 == m1, "재시드 시 board_id 매핑이 바뀜(멱등 위반)"
        assert conn.execute("SELECT count(*) FROM board").fetchone()[0] == 19
        assert conn.execute("SELECT count(*) FROM ingest_state").fetchone()[0] == 19


@pytest.mark.integration
def test_seed_excludes_personal_boards(conn) -> None:
    """시드 후 board 테이블에 제외 4보드의 bizbox_board_no 부재."""
    from app.ingest.loader import upsert_board_seed

    with conn.transaction(force_rollback=True):
        upsert_board_seed(conn, BOARDS)
        rows = conn.execute("SELECT bizbox_board_no FROM board").fetchall()
        present = {r[0] for r in rows}
        assert present & EXCLUDED_BOARD_NOS == set()
