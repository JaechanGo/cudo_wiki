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
from mcp.server.transport_security import TransportSecuritySettings

from app.common.config import get_settings
from app.common.db import close_pool, healthcheck, open_pool
from app.common.logging import configure_logging, get_logger
from app.mcp.tools import register_all

_settings = get_settings()
configure_logging(_settings.log_level)
_log = get_logger("app.mcp.server")

_INSTRUCTIONS = (
    "CUDO 사내 위키 MCP — 사내 규정·전결·공지·매뉴얼·회사문서 검색/인용. 도구 8종"
    "(search_regulations·get_regulation·get_attachment·list_boards·list_recent_posts·"
    "get_approval_authority·aggregate_compare·get_regulation_diff). 핵심 규칙:\n"
    "① 라우팅: 사내 업무·제도 질문(규정·전결·결재·경비/정산·복지·수당·휴가·마감/일정·"
    "신청/양식·공지, 그리고 사업자등록증·법인등기 등 회사가 사내에 게시한 문서 포함)은 "
    "키워드에 '규정'이 없어도 반드시 search_regulations 로 먼저 검색하라. 웹 검색을 쓰지 말고"
    "(사내 정보는 외부에 없다), '민감정보'를 이유로 거절하거나 외부 부서로 돌리지 마라. "
    "근거를 못 찾으면 사내 출처가 없음을 알리고 기권하라.\n"
    "② 최신성: 항상 현행(최신)을 답하라. 검색 결과는 최신순 정렬이므로 **최상단(첫 번째) 항목이 "
    "현행**이다. 특정 문서를 요청받으면 매번 새로 검색하고, 직전 턴의 결과·attachment_id 를 "
    "재사용하지 마라(과거 판본 오답 방지). 과거 자료는 '과거/개정 전'으로 분리해 표기하라. "
    "'최신/최근 공지(글)를 보여줘'처럼 키워드가 아니라 **시간순 목록**이 의도인 요청은 "
    "search_regulations 가 아니라 **list_recent_posts**(board 로 게시판명 필터) 를 써라 — "
    "렉시컬 검색은 '공지/최신' 토큰이 많은 옛 글을 위로 올린다.\n"
    "③ 출처·첨부 링크: 검색 출처(source)나 get_attachment 응답에 첨부 download_url 이 있으면, "
    "**각 첨부를 반드시 `[파일명](download_url)` 마크다운 링크로 제시**하라 — 응답 메타의 "
    "download_url 값을 **그대로** 쓰고 링크를 **비우거나 생략하지 마라**(축약·변형·생성도 금지). "
    "사용자가 그 링크를 클릭해 원문을 받는다. 조번호 임의생성 금지. "
    "`turn0…` 같은 자리표시 인용 토큰은 만들지 마라(raw 로 노출됨).\n"
    "④ 신원·권한은 인증 세션 헤더 기반으로 자동 적용된다(ACL·PII 마스킹)."
)

# ★ DNS rebinding 보호 비활성화(Task009 §7.2): 본 서버는 내부 도커망 전용(compose 호스트 포트
# 미공개, networks internal+librechat). FastMCP 기본은 host=127.0.0.1 일 때 보호를 자동 활성화하고
# allowed_hosts 를 localhost 변형으로만 제한 → LibreChat 의 Host(예 'cudo-wiki-mcp:8080')가 거부됨.
# 내부 신뢰망이라 브라우저 기반 DNS rebinding 위협이 없으므로 비활성화한다(외부 노출 시 D 가 재고).
_TRANSPORT_SECURITY = TransportSecuritySettings(enable_dns_rebinding_protection=False)

# streamable_http_path='/' → FastAPI 에서 '/mcp' 로 mount 하면 최종 경로 '/mcp'.
mcp = FastMCP(
    name="cudo-wiki",
    instructions=_INSTRUCTIONS,
    streamable_http_path="/",
    transport_security=_TRANSPORT_SECURITY,
)

# C: 도구 7종 등록(얇은 핸들러 + impl_* 분리) — 앱 생성 전에 등록. 개수는 /healthz 가 보고.
_TOOL_COUNT = register_all(mcp)

# session_manager 는 streamable_http_app() 호출 시 lazy 생성.
_mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # C: 풀을 실제로 연다(wait=False → 비차단, 연결은 lazy/백그라운드). MCP 세션 매니저 구동.
    await open_pool()
    async with mcp.session_manager.run():
        _log.info("cudo-wiki MCP 기동 (도구 %d종)", _TOOL_COUNT)
        yield
    await close_pool()


app = FastAPI(title="cudo-wiki-mcp", version="0.1.0", lifespan=lifespan)
app.mount("/mcp", _mcp_app)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    """라이브니스 — DB 비의존. 도구 등록 개수 보고(스모크 검증용)."""
    return {"status": "ok", "service": "cudo-wiki-mcp", "tools": _TOOL_COUNT}


@app.get("/readyz")
async def readyz() -> dict[str, object]:
    """레디니스 — DB 도달(SELECT 1) 확인. 실패 시 503."""
    from fastapi import Response

    try:
        ok = await healthcheck()
    except Exception as exc:  # 연결 실패 등 — not ready.
        _log.warning("readyz DB 체크 실패: %s", exc)
        ok = False
    if not ok:
        return Response(status_code=503)
    return {"status": "ready", "service": "cudo-wiki-mcp"}
