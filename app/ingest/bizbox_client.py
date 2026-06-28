"""BizBox 그룹웨어 HTTP 경계 (plan §1·§5·§9, DESIGN §7).

``BizboxClient`` Protocol 로 HTTP 경계를 추상화해 목 주입점을 만든다:
- ``HttpBizboxClient``: 실세션(httpx.Client cookie jar, JSESSIONID). 서비스계정 프로그램 로그인은
  ``Settings``(.env)에서 자격을 읽는다(**비번 하드코딩 금지**). 엔드포인트는 DESIGN §7.
- ``MockBizboxClient``: fixture 디렉터리(``tests/fixtures/bizbox/<board_no>/``) 기반. login no-op.

BizBox 는 **읽기 크롤만**(쓰기/변경 절대 금지).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import parse_qs, urlsplit

if TYPE_CHECKING:
    import httpx

    from app.common.config import Settings


@runtime_checkable
class BizboxClient(Protocol):
    """BizBox HTTP 경계. 실세션/목이 동일 인터페이스를 만족(목 주입점)."""

    def login(self) -> None:
        """서비스계정 프로그램 로그인 → 세션 쿠키(JSESSIONID) 확보."""
        ...

    def fetch_board_page(self, board_no: int, page: int, per_page: int) -> str:
        """목록 HTML(viewBoard.do)."""
        ...

    def fetch_post(self, board_no: int, art_no: int) -> str:
        """글 HTML(viewPost.do) — 메타 + iframe(bizboxLink.do) 포함."""
        ...

    def fetch_inner_content(self, bizbox_link_url: str) -> str:
        """2-hop 본문 HTML(디코드된 실 EDMS 경로 요청)."""
        ...

    def download_attachment(self, url: str, params: dict) -> bytes:
        """첨부 바이트."""
        ...


# ── 실세션 ───────────────────────────────────────────────────────────────────

# DESIGN §7 엔드포인트.
_BOARD_LIST_PATH = "/edms/board/viewBoard.do"
_POST_VIEW_PATH = "/edms/board/viewPost.do"
_DOWNLOAD_PATHS = (
    "/gw/cmm/file/edmsDownloadProc.do",  # 메인
    "/edms/board/downloadFile.do",       # 폴백 1
    "/edms/doc/downloadFile.do",          # 폴백 2
)


class HttpBizboxClient:
    """실세션 BizBox 클라이언트(httpx.Client, cookie jar). 폐쇄망 스모크 전용."""

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
        self._base = settings.bizbox_base.rstrip("/")
        self._timeout = timeout
        self._client = http_client
        self._logged_in = False

    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            import httpx

            self._client = httpx.Client(
                base_url=self._base, timeout=self._timeout, follow_redirects=True
            )
        return self._client

    def login(self) -> None:
        """서비스계정 프로그램 로그인. 자격은 Settings(.env) — 하드코딩 금지."""
        client = self._ensure_client()
        user = self._settings.bizbox_user
        password = self._settings.bizbox_password
        if not user:
            raise RuntimeError("BIZBOX_USER 미설정(.env) — 서비스계정 로그인 불가")
        # 로그인 폼 POST(엔드포인트는 환경별 — 스모크 시 확정). 쿠키는 client jar 에 적재.
        client.post("/gw/login/loginProcess.do", data={"userId": user, "passwd": password})
        self._logged_in = True

    def fetch_board_page(self, board_no: int, page: int, per_page: int) -> str:
        resp = self._ensure_client().get(
            _BOARD_LIST_PATH,
            params={"boardNo": board_no, "currentPage": page, "countPerPage": per_page},
        )
        resp.raise_for_status()
        return resp.text

    def fetch_post(self, board_no: int, art_no: int) -> str:
        resp = self._ensure_client().get(
            _POST_VIEW_PATH, params={"boardNo": board_no, "artNo": art_no}
        )
        resp.raise_for_status()
        return resp.text

    def fetch_inner_content(self, bizbox_link_url: str) -> str:
        resp = self._ensure_client().get(bizbox_link_url)
        resp.raise_for_status()
        return resp.text

    def download_attachment(self, url: str, params: dict) -> bytes:
        resp = self._ensure_client().get(url or _DOWNLOAD_PATHS[0], params=params)
        resp.raise_for_status()
        return resp.content

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


# ── 목(fixture) ──────────────────────────────────────────────────────────────


class MockBizboxClient:
    """fixture 디렉터리 기반 목. 실네트워크 없이 "1보드 크롤→DB 적재" 검증(plan §9).

    레이아웃: ``<fixtures_dir>/<board_no>/{board_p<page>.html, post_<artNo>.html,
    inner_<artNo>.html, <saveFileName>}``. login no-op.
    """

    def __init__(self, fixtures_dir: str | Path) -> None:
        self._root = Path(fixtures_dir)

    def login(self) -> None:
        pass  # no-op

    def _read(self, board_no: int, name: str) -> str:
        return (self._root / str(board_no) / name).read_text(encoding="utf-8")

    def fetch_board_page(self, board_no: int, page: int, per_page: int) -> str:
        path = self._root / str(board_no) / f"board_p{page}.html"
        if not path.exists():
            return "<table class='board-list'><tbody></tbody></table>"
        return path.read_text(encoding="utf-8")

    def fetch_post(self, board_no: int, art_no: int) -> str:
        return self._read(board_no, f"post_{art_no}.html")

    def fetch_inner_content(self, bizbox_link_url: str) -> str:
        """디코드된 실경로의 query(boardNo/artNo)로 inner fixture 를 해소."""
        q = parse_qs(urlsplit(bizbox_link_url).query)
        art_no = q.get("artNo", [None])[0]
        board_no = q.get("boardNo", [None])[0]
        if art_no is None:
            raise FileNotFoundError(f"inner fixture 해소 불가(artNo 없음): {bizbox_link_url}")
        if board_no is not None:
            return self._read(int(board_no), f"inner_{art_no}.html")
        # boardNo 없으면 모든 보드 디렉터리에서 inner_<artNo>.html 탐색.
        for board_dir in self._root.iterdir():
            cand = board_dir / f"inner_{art_no}.html"
            if cand.exists():
                return cand.read_text(encoding="utf-8")
        raise FileNotFoundError(f"inner fixture 없음: artNo={art_no}")

    def download_attachment(self, url: str, params: dict) -> bytes:
        """url/params 의 boardNo + saveFileName 으로 첨부 fixture 바이트를 해소."""
        merged: dict[str, str] = {}
        if url:
            for k, v in parse_qs(urlsplit(url).query).items():
                merged[k] = v[0]
        for k, v in (params or {}).items():
            if v is not None:
                merged[k] = str(v)
        board_no = merged.get("boardNo")
        save_name = merged.get("saveFileName") or merged.get("fileNm")
        if board_no is None or save_name is None:
            raise FileNotFoundError(f"첨부 fixture 해소 불가(boardNo/saveFileName): {merged}")
        return (self._root / str(board_no) / save_name).read_bytes()
