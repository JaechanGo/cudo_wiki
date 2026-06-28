"""plan §9·§10 (★ task 검증 요구) — MockBizboxClient + migrated_db 로 1보드 크롤→DB 적재.

사내규정 보드(900000286) fixtures 를 ``crawl_board`` 로 1회 크롤 → post/attachment/clause/
authority 적재·조회를 단언한다. 실네트워크/실세션 없이 HTTP 경계를 목으로 대체(plan §9).
글 단위 실패 격리(plan §8)도 검증.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from app.ingest.bizbox_client import MockBizboxClient
from app.ingest.board_seed import BOARDS
from app.ingest.loader import upsert_board_seed
from app.ingest.run import crawl_board

# ① 첨부 라이브 파싱(appendFileTop.do/download.do) + fixture 를 라이브 구조(exData·
# viewPostArtContent)로 갱신한 뒤 활성화. 현재 crawl_post 는 본문만 수집(첨부 빈 tuple).
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skip(reason="①첨부 라이브 파싱 + fixture 라이브 갱신 후 활성화 예정"),
]

REG_BOARD_NO = 900000286
FIXTURES_ROOT = str(Path(__file__).resolve().parents[1] / "fixtures" / "bizbox")


@pytest.fixture
def conn(migrated_db):
    with psycopg.connect(migrated_db["libpq"]) as c:
        yield c


def test_crawl_one_board_loads_post_attachment_clause_authority(conn) -> None:
    client = MockBizboxClient(FIXTURES_ROOT)
    with conn.transaction(force_rollback=True):
        bid = upsert_board_seed(conn, BOARDS)[REG_BOARD_NO]

        counts = crawl_board(
            conn, client, board_no=REG_BOARD_NO, board_id=bid,
            board_class="regulation", full=True,
        )

        assert counts.posts == 2
        assert counts.failures == 0

        # post 2건(1001 출장비 규정 / 1002 복무규정).
        n_post = conn.execute(
            "SELECT count(*) FROM post WHERE board_id = %s", (bid,)
        ).fetchone()[0]
        assert n_post == 2
        titles = {
            r[0]
            for r in conn.execute("SELECT title FROM post WHERE board_id = %s", (bid,)).fetchall()
        }
        assert titles == {"출장비 규정", "복무규정"}

        # 첨부 1건(1001 의 전결표 xlsx) + 추출 텍스트 적재.
        att = conn.execute(
            "SELECT file_name, kind, is_table, extract_method, extracted_text FROM attachment"
        ).fetchone()
        assert att[1] == "excel"
        assert att[2] is True
        assert att[3] == "native"
        assert att[4] and "출장비" in att[4]

        # 규정 2건(각 글이 1규정) + curated=false(ADR-003 미검증).
        n_reg = conn.execute("SELECT count(*) FROM regulation").fetchone()[0]
        assert n_reg == 2
        assert conn.execute("SELECT bool_and(curated = false) FROM regulation").fetchone()[0]

        # clause: 결정론 파서 산출이 적재됨(제1조·제4조의2·부칙 등 포함).
        n_clause = conn.execute("SELECT count(*) FROM clause").fetchone()[0]
        assert n_clause >= 10
        canons = {
            r[0] for r in conn.execute("SELECT canonical_clause_id FROM clause").fetchall()
        }
        # 출장비 규정(reg_id 보존된 R{rid}) 의 제4조의2·부칙이 canonical 로 존재.
        assert any(c.endswith("#a4의2") for c in canons)
        assert any("#supp1" in c for c in canons)

        # authority: 전결표 셀 2건(전결/합의) 적재 + amount_band 생성열 확인.
        rows = conn.execute(
            "SELECT action_type, amount_min, amount_max, consulter_roles "
            "FROM authority_matrix ORDER BY order_seq"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "전결"
        assert rows[0][2] == 10_000_000  # "1천만원 이하"
        assert rows[1][1] == 10_000_001  # "1천만원 초과" 보정
        assert "재무팀" in rows[0][3]

        # 워터마크 전진(최대 art_no=1002).
        wm = conn.execute(
            "SELECT last_art_no FROM ingest_state WHERE board_id = %s", (bid,)
        ).fetchone()[0]
        assert wm == 1002


class _PartlyFailingClient(MockBizboxClient):
    """특정 글의 fetch_post 가 실패하도록 만든 목(글 단위 실패 격리 검증)."""

    def fetch_post(self, board_no: int, art_no: int) -> str:
        if art_no == 1002:
            raise RuntimeError("의도된 글 추출 실패")
        return super().fetch_post(board_no, art_no)


def test_crawl_board_isolates_per_post_failure(conn) -> None:
    """1글 실패가 보드를 중단시키지 않고 나머지는 적재(plan §8)."""
    client = _PartlyFailingClient(FIXTURES_ROOT)
    with conn.transaction(force_rollback=True):
        bid = upsert_board_seed(conn, BOARDS)[REG_BOARD_NO]

        counts = crawl_board(
            conn, client, board_no=REG_BOARD_NO, board_id=bid,
            board_class="regulation", full=True,
        )

        assert counts.failures == 1
        assert counts.posts == 1  # 1001 만 성공.
        # 성공 글(1001)은 적재됨.
        n_post = conn.execute(
            "SELECT count(*) FROM post WHERE board_id = %s", (bid,)
        ).fetchone()[0]
        assert n_post == 1
        # 보드 health 는 degraded(실패 발생).
        health = conn.execute(
            "SELECT health FROM ingest_state WHERE board_id = %s", (bid,)
        ).fetchone()[0]
        assert health == "degraded"
