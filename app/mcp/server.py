"""streamable-http MCP 서버 — R0 골격 (도구 0개) + /healthz.

DESIGN §2: LibreChat 가 ``http://cudo-wiki-mcp:<PORT>/mcp`` 로 도달, serverInstructions 노출.
R0 범위: 기동만 검증. 도구 7종(search_regulations·get_regulation·get_attachment·list_boards·
         get_approval_authority·aggregate_compare·get_regulation_diff)은 C 서브시스템 후속.

기동: uvicorn app.mcp.server:app --host 0.0.0.0 --port ${MCP_PORT}
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

from app.common.config import get_settings
from app.common.db import close_pool, get_pool
from app.common.logging import configure_logging, get_logger

_settings = get_settings()
configure_logging(_settings.log_level)
_log = get_logger("app.mcp.server")

_INSTRUCTIONS = (
    "CUDO 사내 위키 MCP — 사내 규정/전결규정/공지/매뉴얼 검색·인용. "
    "인용은 메타데이터 결정론(LLM 조번호 생성 금지), 근거 없으면 기권. "
    "(R0 골격: 도구 미구현 — 후속 태스크에서 7종 추가.)"
)

# session_manager 는 streamable_http_app() 호출 시 lazy 생성되므로 먼저 앱을 만든다.
# streamable_http_path='/' → FastAPI 에서 '/mcp' 로 mount 하면 최종 경로 '/mcp'.
mcp = FastMCP(name="cudo-wiki", instructions=_INSTRUCTIONS, streamable_http_path="/")
_mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # R0: 풀 객체만 lazy 생성(연결은 도구 구현 후 open_pool 로). MCP 세션 매니저 구동.
    get_pool()
    async with mcp.session_manager.run():
        _log.info("cudo-wiki MCP 기동 (R0 골격, 도구 0개)")
        yield
    await close_pool()


app = FastAPI(title="cudo-wiki-mcp", version="0.1.0", lifespan=lifespan)
app.mount("/mcp", _mcp_app)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    """라이브니스 — DB 비의존(R0). 도구 구현 후 readiness 는 별도."""
    return {"status": "ok", "service": "cudo-wiki-mcp", "tools": 0}
