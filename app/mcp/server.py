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
    "CUDO 사내 위키 MCP — 사내 규정/전결규정/공지/매뉴얼 검색·인용. "
    "도구 7종(search_regulations·get_regulation·get_attachment·list_boards·"
    "get_approval_authority·aggregate_compare·get_regulation_diff). "
    "★ 라우팅 원칙: CUDO 사내 업무·제도에 관한 질문(규정·전결·결재·경비/정산·"
    "복지·수당·휴가·일정/마감·신청/절차·양식·공지·매뉴얼 등)은 키워드가 명시적으로 "
    "'규정/전결'을 포함하지 않더라도 **반드시 이 MCP 도구로 먼저 검색**하라"
    "(사내 정보 질문의 기본 진입점 = search_regulations). 이런 질문에 **웹 검색을 "
    "쓰지 말 것** — 사내 정보는 외부 웹에 없다. 도구로 근거를 찾지 못하면 웹으로 추측하지 "
    "말고 사내 출처가 없음을 안내하며 기권하라. "
    "★ 사내 공지 문서: 사업자등록증·법인등기·회사소개·증명서 등 회사가 사내 게시판에 게시한 "
    "문서는 직원 대상 사내 공지물이다. '민감정보/개인정보'를 이유로 거절하거나 외부(총무팀 등)로 "
    "돌리지 말고, 다른 사내 질문과 동일하게 search_regulations 로 검색해 출처·첨부 링크를 제공하라. "
    "★ 최신성 원칙: 사내 정보는 항상 **현행(최신) 버전**을 답으로 제시하라. 도구 결과는 "
    "이미 현행만 필터(is_current)된 결정론 메타데이터이므로, 어느 판본이 현행인지 임의로 "
    "추측('…인 것으로 보입니다')하지 말 것. 과거·개정 전 내용이 함께 보이면 반드시 "
    "'과거/개정 전'으로 명시해 분리하고 현행 답변에 섞지 마라. 개정 이력·시행일 비교가 "
    "필요하면 get_regulation_diff·시행일(effective_date) 메타를 사용하라. "
    "★★ 특정 문서/규정(예: 사업자등록증)을 요청받으면, 직전 턴에서 본 결과나 attachment_id 를 "
    "재사용하지 말고 **매번 search_regulations 로 새로 검색**하라. 검색 결과는 최신순으로 정렬되어 "
    "있으므로 **최상단(첫 번째) 항목이 현행**이다 — 하단의 오래된 판본(예: 2016년 자료)을 답으로 "
    "고르지 말 것. 첨부 원본이 필요하면 그 **현행(최상단) 글의 첨부 id** 로 get_attachment 를 호출하라. "
    "인용은 메타데이터 결정론(LLM 조번호 생성 금지), 근거 없으면 기권. "
    "★ 첨부 링크: 검색 결과 출처(source)에 첨부(attachments)가 있으면, 각 첨부를 "
    "**`[파일명](download_url)` 마크다운 링크**로 답변에 제시하라(download_url 은 이미 "
    "절대 URL). 사용자가 클릭하면 BizBox 에서 원문(양식·전결표 등)을 직접 받는다. "
    "URL 을 바꾸거나 새로 만들지 말고 메타의 download_url 을 그대로 쓸 것. "
    "★ 인용 표기: `turn0…`·`turn0get_attachment0` 같은 자리표시 인용 토큰을 본문에 만들지 "
    "마라(렌더링되지 않고 raw 문자열로 노출됨). 출처·첨부 링크는 오직 `[제목/파일명](url)` 마크다운 "
    "형식으로만 제시하라. "
    "신원·권한은 인증세션 헤더 기반(ACL/PII 마스킹). "
    "aggregate_compare 는 v1 에서 보드별 현행 규정 카운트 비교만 지원(차집합·추세 미지원)."
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
