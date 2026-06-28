"""plan §6 — ocr-shim HTTP 클라이언트 계약 검증 (httpx MockTransport, 실네트워크 없음).

계약(plan §6): ``POST {ocr_base}/v1/ocr``,
body ``{document:{document_url:"data:application/pdf;base64,.."}}`` → 응답 ``pages[].markdown``.
페이지별 ExtractedPage 로 매핑, method='ocr-shim'.
HTTP 경계라 client 주입으로 목 가능(함수/클라이언트 분리).
"""

from __future__ import annotations

import base64
import json

import httpx

from app.ingest.extract.ocr import OcrClient, extract_via_ocr

_PDF_BYTES = b"%PDF-1.4 scanned content bytes"


def _make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ocr-shim:8900")


def test_ocr_request_body_is_base64_pdf_data_url() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"pages": [{"markdown": "본문"}]})

    client = OcrClient(base_url="http://ocr-shim:8900", http_client=_make_client(handler))
    client.ocr(_PDF_BYTES)

    assert captured["url"].endswith("/v1/ocr")
    data_url = captured["body"]["document"]["document_url"]
    assert data_url.startswith("data:application/pdf;base64,")
    decoded = base64.b64decode(data_url.split(",", 1)[1])
    assert decoded == _PDF_BYTES


def test_ocr_parses_pages_markdown() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"pages": [{"markdown": "# 1쪽"}, {"markdown": "표 내용"}]},
        )

    client = OcrClient(base_url="http://ocr-shim:8900", http_client=_make_client(handler))
    pages = client.ocr(_PDF_BYTES)

    assert [p.page_no for p in pages] == [1, 2]
    assert pages[0].ocr_text == "# 1쪽"
    assert pages[1].ocr_text == "표 내용"


def test_extract_via_ocr_builds_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"pages": [{"markdown": "A"}, {"markdown": "B"}]})

    client = OcrClient(base_url="http://ocr-shim:8900", http_client=_make_client(handler))
    result = extract_via_ocr(_PDF_BYTES, client)

    assert result.method == "ocr-shim"
    assert result.ocr_status == "done"
    assert result.page_count == 2
    assert "A" in result.extracted_text and "B" in result.extracted_text
    assert len(result.pages) == 2


def test_extract_via_ocr_failure_is_graceful() -> None:
    """OCR 서버 5xx → 예외로 보드 중단 금지 → status='failed' + error_msg."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    client = OcrClient(base_url="http://ocr-shim:8900", http_client=_make_client(handler))
    result = extract_via_ocr(_PDF_BYTES, client)

    assert result.ocr_status == "failed"
    assert result.error_msg
    assert result.extracted_text is None or result.extracted_text == ""
