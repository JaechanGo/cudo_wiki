"""BizBox 그룹웨어 HTTP 경계 (plan §1·§5·§9, DESIGN §7).

``BizboxClient`` Protocol 로 HTTP 경계를 추상화해 목 주입점을 만든다:
- ``HttpBizboxClient``: 실세션(httpx.Client cookie jar, JSESSIONID). 서비스계정 프로그램 로그인은
  ``Settings``(.env)에서 자격을 읽는다(**비번 하드코딩 금지**). 엔드포인트는 DESIGN §7.
- ``MockBizboxClient``: fixture 디렉터리(``tests/fixtures/bizbox/<board_no>/``) 기반. login no-op.

BizBox 는 **읽기 크롤만**(쓰기/변경 절대 금지).
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import parse_qs, quote, urlsplit

from cryptography.hazmat.primitives import padding as _sympad
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

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

# eGov + Spring Security 로그인 (라이브 실측 2026-06-29). 로그인 페이지의 securityEncrypt() 재현.
_LOGIN_PAGE_PATH = "/gw/uat/uia/egovLoginUsr.do"
_ACTION_LOGIN_PATH = "/gw/uat/uia/actionLogin.do"
# 로그인 페이지 JS 의 정적 AES 키(전사 동일·공개 — 비밀 아님). key == iv, AES-128-CBC-PKCS7.
_LOGIN_AES_KEY = b"jIBQW9QlRqV#DT(C"


def _security_encrypt(plain: str) -> str:
    """로그인 페이지 ``securityEncrypt()`` 재현: AES-128-CBC-PKCS7 → base64 → ``'!'+`` → encodeURIComponent."""
    padder = _sympad.PKCS7(128).padder()
    padded = padder.update(plain.encode("utf-8")) + padder.finalize()
    enc = Cipher(algorithms.AES(_LOGIN_AES_KEY), modes.CBC(_LOGIN_AES_KEY)).encryptor()
    ct = enc.update(padded) + enc.finalize()
    return quote("!" + base64.b64encode(ct).decode(), safe="!*'()")


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
        """서비스계정 프로그램 로그인 (eGov + Spring Security 3단계, AES 암호화 — 라이브 실측).

        ① 로그인 페이지 GET(세션·anti-bot 토큰 확보) → ② actionLogin.do 에 AES 암호화
        id/password POST(Referer 필수) → Spring Security 자동제출 폼 응답 →
        ③ 그 폼(j_username/j_password)을 j_spring_security_check 로 POST → 인증 세션.
        암호화·필드분할은 로그인 페이지 ``actionLogin()`` JS 와 동일. 자격은 .env.
        """
        client = self._ensure_client()
        user = self._settings.bizbox_user
        password = self._settings.bizbox_password
        if not user or not password:
            raise RuntimeError("BIZBOX_USER/PASSWORD 미설정(.env) — 서비스계정 로그인 불가")

        client.get(_LOGIN_PAGE_PATH)  # ① 세션·토큰

        enc_id = _security_encrypt(user)
        id0, id1, id2 = enc_id, "", ""
        if len(id0) > 50:  # 암호화 id 50자 초과 시 id/id_sub1/id_sub2 분할(JS 동일)
            id1, id0 = id0[50:], id0[:50]
            if len(id1) > 50:
                id2, id1 = id1[50:], id1[:50]

        # ② actionLogin → Spring Security 자동제출 폼
        action_resp = client.post(
            _ACTION_LOGIN_PATH,
            data={
                "isScLogin": "", "scUserId": "", "scUserPwd": "",
                "id": id0, "id_sub1": id1, "id_sub2": id2,
                "password": _security_encrypt(password), "checkId": "",
            },
            headers={"Referer": self._base + _LOGIN_PAGE_PATH},
        )
        m_action = re.search(r"action='([^']+)'", action_resp.text)
        m_user = re.search(r"name='j_username'\s+value='([^']*)'", action_resp.text)
        m_pwd = re.search(r"name='j_password'\s+value='([^']*)'", action_resp.text)
        if not (m_action and m_user and m_pwd):
            raise RuntimeError(
                "BizBox 로그인 실패 — actionLogin 응답에 Spring Security 폼 없음(자격/차단 확인)"
            )

        # ③ Spring Security check → 인증 세션 확정
        client.post(
            m_action.group(1),
            data={"j_username": m_user.group(1), "j_password": m_pwd.group(1)},
            headers={"Referer": self._base},
        )
        self._logged_in = True

    def fetch_board_page(self, board_no: int, page: int, per_page: int) -> str:
        resp = self._ensure_client().get(
            _BOARD_LIST_PATH,
            params={"boardNo": board_no, "currentPage": page, "countPerPage": per_page},
        )
        resp.raise_for_status()
        return resp.text

    def fetch_post(self, board_no: int, art_no: int) -> str:
        """viewPost.do GET — listForm 필드(name=artNo, remarkNo=-1 등) 전체 + Referer(라이브 실측).

        articleNo 가 아니라 **name=artNo**(폼 input id=articleNo, 전송 name=artNo)로 보내야
        "읽기 권한 없음" 응답을 피한다. listForm 의 정렬/검색 hidden 도 함께 전송(브라우저 동등).
        """
        resp = self._ensure_client().get(
            _POST_VIEW_PATH,
            params={
                "boardNo": board_no,
                "artNo": art_no,
                "currentPage": 1,
                "remarkNo": -1,
                "siteflag": -1,
                "sorting": "sortOrderSort",
                "sortOrderSort": "asc",
                "searchField": "",
                "searchValue": "",
                "startDate": "",
                "endDate": "",
                "countPerPage": 30,
                "attentionCnt": 0,
            },
            headers={"Referer": self._base + _BOARD_LIST_PATH},
        )
        resp.raise_for_status()
        return resp.text

    def fetch_inner_content(self, bizbox_link_url: str) -> str:
        """2-hop 본문(viewPostArtContent.do) GET. crawler 가 만든 상대경로를 그대로 요청."""
        resp = self._ensure_client().get(
            bizbox_link_url, headers={"Referer": self._base + _POST_VIEW_PATH}
        )
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
