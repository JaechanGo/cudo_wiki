"""gainge 지식뱅크 GraphQL 경계 (cudo.gainge.com, 영상 소스).

BizBox(HttpBizboxClient)와 달리 gainge 는 단일 GraphQL 엔드포인트(POST /api/graphql)로
카테고리·게시글을 조회한다. 인증은 **순수 쿠키 세션**(JWT/Authorization 헤더 없음, 실측 2026-06-29)
이라 ``Settings.gainge_session_cookie``(브라우저 Cookie 헤더 전체 문자열)를 그대로 주입한다
(bizbox_jsessionid 와 동일한 anti-bot 우회 임시수단 — 세션 만료 시 재발급 필요).

읽기 크롤만(쓰기 절대 금지). ``_cache`` 는 list_post_refs↔crawl_post 간 게시글 dict 공유용
(목록 조회 시 content/clip 까지 한 번에 받으므로 상세 재조회를 줄인다).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

    from app.common.config import Settings

_GRAPHQL_PATH = "/api/graphql"

# anti-bot 회피용 브라우저 시그니처(읽기 크롤). bizbox 와 동일 취지, 모듈 독립 보존.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
}


class GaingeClient:
    """실세션 gainge 클라이언트(httpx.Client + 쿠키헤더). GraphQL 단일 진입 graphql()."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if settings is None:
            from app.common.config import get_settings

            settings = get_settings()
        self._settings = settings
        self._base = settings.gainge_base.rstrip("/")
        self._timeout = timeout
        self._client = http_client
        # list_post_refs 가 채우고 crawl_post 가 소비하는 게시글 dict 캐시(seq → post).
        self._cache: dict[int, dict[str, Any]] = {}

    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            import httpx

            headers = dict(_BROWSER_HEADERS)
            cookie = (self._settings.gainge_session_cookie or "").strip()
            if cookie:
                headers["Cookie"] = cookie
            self._client = httpx.Client(
                base_url=self._base, timeout=self._timeout,
                follow_redirects=True, headers=headers,
            )
        return self._client

    def login(self) -> None:
        """쿠키세션 검증 — 쿠키는 헤더로 이미 주입됨. 미설정이면 즉시 실패(자동로그인 없음)."""
        if not (self._settings.gainge_session_cookie or "").strip():
            raise RuntimeError(
                "GAINGE_SESSION_COOKIE 미설정(.env) — gainge 는 쿠키세션만 지원(자동로그인 불가)"
            )
        self._ensure_client()

    def graphql(
        self, operation_name: str, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """GraphQL POST → data 딕셔너리. errors 동반 시 RuntimeError(호출부 격리)."""
        resp = self._ensure_client().post(
            _GRAPHQL_PATH,
            json={
                "operationName": operation_name,
                "variables": variables or {},
                "query": query,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise RuntimeError(f"gainge GraphQL 오류({operation_name}): {payload['errors']}")
        return payload.get("data") or {}

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
