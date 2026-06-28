"""BizBox 로그인 라이브 진단 — 서버 IP 차단 vs 자격거부 구분.

실행(컨테이너): ``python -m app.ingest.diag``
자격값은 노출하지 않고(길이만), actionLogin.do 응답의 Spring Security 폼 유무·차단 키워드·
본문 앞부분만 출력한다. 읽기 전용(쓰기/로그인 세션 영속 없음).
"""

from __future__ import annotations

import httpx

from app.common.config import get_settings
from app.ingest.bizbox_client import (
    _ACTION_LOGIN_PATH,
    _BROWSER_HEADERS,
    _LOGIN_PAGE_PATH,
    _security_encrypt,
)


def main() -> int:
    s = get_settings()
    base = s.bizbox_base.rstrip("/")
    print(f"[cfg] USER_len={len(s.bizbox_user or '')} PW_len={len(s.bizbox_password or '')} BASE={base}")
    if not s.bizbox_user or not s.bizbox_password:
        print("[!] 자격 미설정 — .env 의 BIZBOX_USER/PASSWORD 확인 후 컨테이너 재시작")
        return 2

    cli = httpx.Client(
        base_url=base, timeout=30.0, follow_redirects=True, headers=_BROWSER_HEADERS
    )

    r1 = cli.get(_LOGIN_PAGE_PATH)
    blocked1 = ("비정상" in r1.text) or ("차단" in r1.text)
    print(f"[1] egovLoginUsr.do: status={r1.status_code} len={len(r1.text)} 차단문구={blocked1}")

    enc_id = _security_encrypt(s.bizbox_user)
    i0, i1, i2 = enc_id, "", ""
    if len(i0) > 50:
        i1, i0 = i0[50:], i0[:50]
        if len(i1) > 50:
            i2, i1 = i1[50:], i1[:50]

    r2 = cli.post(
        _ACTION_LOGIN_PATH,
        data={
            "isScLogin": "", "scUserId": "", "scUserPwd": "",
            "id": i0, "id_sub1": i1, "id_sub2": i2,
            "password": _security_encrypt(s.bizbox_password), "checkId": "",
        },
        headers={"Referer": base + _LOGIN_PAGE_PATH},
    )
    has_form = "j_username" in r2.text
    print(f"[2] actionLogin.do: status={r2.status_code} len={len(r2.text)} j_username폼={has_form}")
    for kw in ("비정상", "차단", "오류", "실패", "IP", "허용", "접근"):
        if kw in r2.text:
            print(f"    키워드 발견: {kw!r}")
    print(f"[2] 본문 앞부분: {r2.text[:600].replace(chr(10), ' ')}")

    if has_form:
        print("[=>] actionLogin 폼 정상 — 로그인 흐름 OK (login() 성공해야 함)")
        return 0
    print("[=>] 폼 없음 — 서버 IP 차단 또는 자격거부. 위 본문/키워드로 판별.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
