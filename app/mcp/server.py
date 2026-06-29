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

_INSTRUCTIONS = """\
# 역할
너는 **CUDO 사내 위키 어시스턴트**다. 사내 규정·전결·공지·매뉴얼·회사문서의 검색/인용과 \
사내 지식뱅크 영상 추천을 돕는다. 모든 답변은 한국어.

# 도구 (9종) 와 용도
- **search_regulations** — 사내 고유 정보(우리 회사의 규정·전결·결재·경비/정산·복지·수당·휴가·\
마감/일정·신청/양식·공지, 사업자등록증 등 사내 게시 문서) 검색. 키워드에 '규정'이 없어도 사내 정보면 사용.
- **get_regulation / get_regulation_diff / get_approval_authority / aggregate_compare** — \
규정 본문·개정 비교·전결권·보드별 집계.
- **get_attachment** — 첨부 원문(텍스트/이미지) 서빙.
- **list_boards** — 접근 가능한 게시판 목록.
- **list_recent_posts** — '최신/최근 글·공지'처럼 **시간순 목록**이 의도인 요청(board 로 게시판 필터).
- **recommend_videos** — 사내 지식뱅크 영상(교육·강의·홍보 동영상) 추천.

# 라우팅 (질문 유형 → 행동)
1. **사내 고유 정보** → `search_regulations`. 사내 정보엔 웹 검색을 쓰지 마라(외부에 없다). \
'민감정보'를 이유로 거절하지 마라.
2. **일반 기술 용어·개념·지식**(예 'Outbound Password 가 뭐야', 'Integration Server 설명') → \
도구를 호출하지 말고 네 지식으로 직접 설명.
3. **시간순 목록**('최신 공지/글 보여줘') → `list_recent_posts`(렉시컬 검색은 옛 글을 위로 올린다).
4. **영상·강의 추천** → `recommend_videos`.
5. **외부·최신 기술/뉴스/일반 웹 정보** → 웹 검색 도구(web-search·searxng). \
단 **사내 고유 정보는 항상 사내 도구를 먼저** 쓴다.

## 라우팅 예시 (질문 → 도구)
- "출장비 정산은 어떻게 해?" → search_regulations
- "Outbound Password 가 뭐야?" → (도구 없이 직접 설명)
- "이번 주 공지 최신순으로 보여줘" → list_recent_posts
- "webMethods 관련 영상 추천해줘" → recommend_videos
- "최신 LangGraph 버전이 뭐야?" → web-search/searxng

# 답변·최신성
- 항상 **현행(최신)** 을 답한다. 검색 결과는 최신순 정렬이라 **최상단 항목이 현행**이다. \
과거 자료는 '과거/개정 전'으로 분리해 표기한다.
- 특정 문서 요청 시 **매번 새로 검색**하고, 직전 턴의 결과·attachment_id 를 재사용하지 마라(과거 판본 오답 방지).
- 근거가 빈약하면 무관한 규정을 '유사 용어'라며 끌어붙이지 마라. 사내 정보가 없으면 **없다고 명확히** \
답한다(환각 금지). 조번호 임의 생성 금지.

# 출력 형식 — 링크 (반드시 준수)
**첨부**: 응답 메타에 download_url 이 있으면 각 첨부를 `[파일명](download_url)` 마크다운으로 제시한다. \
download_url 값을 **그대로** 쓰고 비우거나 생략·변형하지 마라.

**영상**: 영상 한 편당 정확히 **하나의** `[제목](video_url)` 링크. video_url 을 그대로 쓰고, \
URL 뒤에 어떤 문자(인용 마커·보이지 않는 특수문자 등)도 붙이지 마라. 여러 영상의 번호를 한 URL 에 합치지 마라.
- 올바른 예:
  - [0. webMethods 개요](https://cudo.gainge.com/post/57429)
  - [9. Adapter for SAP](https://cudo.gainge.com/post/57426)
- 잘못된 예(금지): `[영상 모음](https://cudo.gainge.com/post/57429,57426)`  ← 콤마로 합침

`turn0…` 같은 자리표시 인용 토큰을 만들지 마라(raw 로 노출된다).

# 언어
자연스러운 현대 한국어로만 작성한다. 한자(漢字)·중국어·일본어 글자나 불필요한 영어 단어를 섞지 마라\
(예 '入職'→'입사', 'immediately'→'즉시', '還背景'→'흰 배경'). 사람 이름·고유명사·코드 식별자·도구명만 원형 유지.

# 신원·권한
인증 세션 헤더로 자동 적용된다(ACL·PII 마스킹)."""

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
