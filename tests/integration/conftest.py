"""통합테스트(검색 코어) 공용 async 픽스처 — DB 필요, 없으면 skip (plan §9).

aconn: migrated_db 에 autocommit async 연결. 작은 시드 코퍼스에서 PGroonga 가 seqscan(점수 0)으로
빠지지 않도록 enable_seqscan=off 로 인덱스 사용을 강제(운영은 실코퍼스 → 불필요). 각 테스트는
``async with aconn.transaction(force_rollback=True)`` 로 시드 격리(test_schema.py 패턴 차용).
"""

from __future__ import annotations

import psycopg
import pytest


@pytest.fixture
async def aconn(migrated_db):
    """검색 함수용 psycopg AsyncConnection(autocommit). 함수 스코프, 종료 시 닫음."""
    conn = await psycopg.AsyncConnection.connect(migrated_db["libpq"], autocommit=True)
    try:
        # 소규모 시드에서 pgroonga_score 가 0 이 되지 않도록 인덱스 스캔 강제(테스트 한정 nudge).
        await conn.execute("SET enable_seqscan = off")
        yield conn
    finally:
        await conn.close()
