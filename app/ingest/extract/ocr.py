"""ocr-shim HTTP 클라이언트 (plan §6).

계약: ``POST {ocr_base}/v1/ocr``,
body ``{document:{document_url:"data:application/pdf;base64,.."}}``
→ 응답 ``pages[].markdown``. 페이지별 ``ExtractedPage(page_no, ocr_text)`` 로 매핑.

HTTP 경계를 ``OcrClient`` 로 격리해 테스트에서 ``httpx.Client`` 주입(MockTransport)으로 목 가능.
실패(5xx/타임아웃/형식오류)는 예외를 호출부로 던지지 않고 ``extract_via_ocr`` 가
``ExtractResult(ocr_status='failed', error_msg=...)`` 로 graceful degrade(보드 중단 금지, plan §8).
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

import httpx

from app.ingest.models import ExtractedPage, ExtractResult

if TYPE_CHECKING:
    from collections.abc import Sequence

_OCR_PATH = "/v1/ocr"
_DEFAULT_TIMEOUT = 120.0


class OcrClient:
    """ocr-shim 호출 클라이언트. ``http_client`` 주입 시 그것을 사용(테스트 목 주입점)."""

    def __init__(
        self,
        base_url: str,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = http_client
        self._owns_client = http_client is None

    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self._base_url, timeout=self._timeout)
        return self._client

    @staticmethod
    def _data_url(content: bytes) -> str:
        b64 = base64.b64encode(content).decode("ascii")
        return f"data:application/pdf;base64,{b64}"

    def ocr(self, content: bytes) -> list[ExtractedPage]:
        """PDF/이미지 바이트 → ocr-shim → ExtractedPage 목록(page_no 1-based).

        HTTP 오류는 ``httpx.HTTPStatusError`` 로 raise(상위 ``extract_via_ocr`` 가 잡는다).
        """
        client = self._ensure_client()
        resp = client.post(
            _OCR_PATH,
            json={"document": {"document_url": self._data_url(content)}},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        pages = payload.get("pages") or []
        return [
            ExtractedPage(page_no=idx + 1, ocr_text=(page or {}).get("markdown"))
            for idx, page in enumerate(pages)
        ]

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None


def extract_via_ocr(content: bytes, client: OcrClient) -> ExtractResult:
    """OCR 추출 결과를 ExtractResult 로 포장. 실패는 status='failed' 로 graceful."""
    try:
        pages: Sequence[ExtractedPage] = client.ocr(content)
    except Exception as exc:  # 5xx/타임아웃/형식오류 — 보드 중단 금지(plan §8).
        return ExtractResult(
            method="ocr-shim",
            ocr_status="failed",
            error_msg=f"ocr-shim 호출 실패: {exc}",
        )
    text = "\n\n".join(p.ocr_text for p in pages if p.ocr_text)
    return ExtractResult(
        extracted_text=text or None,
        page_count=len(pages),
        method="ocr-shim",
        ocr_status="done",
        pages=tuple(pages),
    )
