"""DB 연결 — psycopg3 AsyncConnectionPool 싱글톤 (런타임 전용).

런타임은 libpq DSN(``postgresql://``, Settings.dsn)을 psycopg_pool 에 직접 전달.
alembic 은 이 풀을 쓰지 않고 자체 sync Engine(``postgresql+psycopg://``) — 역할 분리(§6.2).

풀은 ``open=False`` 로 생성(생성 시 연결 안 함). 실제 연결은 ``open_pool()``(FastAPI lifespan)에서.
"""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from app.common.config import get_settings

_pool: AsyncConnectionPool | None = None


def get_pool() -> AsyncConnectionPool:
    """프로세스 단일 풀 반환(없으면 lazy 생성, 연결은 아직 안 함)."""
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=get_settings().dsn,
            open=False,
            min_size=1,
            max_size=10,
        )
    return _pool


async def open_pool() -> AsyncConnectionPool:
    """풀을 실제로 연다(연결 수립). lifespan startup 에서 호출."""
    pool = get_pool()
    await pool.open()
    return pool


async def healthcheck() -> bool:
    """``SELECT 1`` 로 DB 도달 확인."""
    pool = get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT 1")
        row = await cur.fetchone()
        return row is not None and row[0] == 1


async def close_pool() -> None:
    """풀 종료. lifespan shutdown 에서 호출."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
