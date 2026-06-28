"""plan §6 — extract_attachment kind 판별 dispatch + hwp graceful + pdf→ocr 폴백.

추출기 선택(kind→hwp/pdf/ocr/excel/native)과 부재 환경 graceful degrade(예외로 보드 중단 금지)를
검증한다. 실제 pyhwp/pypdf 바이너리는 폐쇄망/미설치 전제 → 함수 내부 lazy import 가 실패해도
status='failed' 로만 떨어지고 예외가 전파되지 않아야 한다.
"""

from __future__ import annotations

import io

import httpx
import openpyxl

from app.ingest.extract import extract_attachment
from app.ingest.extract.ocr import OcrClient
from app.ingest.models import RawAttachment


def _xlsx_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["업무항목", "결재구분"])
    ws.append(["비품구매", "전결"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _ocr_client_returning(markdown: str) -> OcrClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"pages": [{"markdown": markdown}]})

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ocr-shim:8900")
    return OcrClient(base_url="http://ocr-shim:8900", http_client=http)


def test_dispatch_excel_marks_table() -> None:
    raw = RawAttachment(file_name="전결표.xlsx", kind="excel", content=_xlsx_bytes())
    result = extract_attachment(raw)
    assert result.is_table is True
    assert result.ocr_status == "done"
    assert "비품구매" in result.extracted_text


def test_dispatch_hwp_graceful_when_no_engine() -> None:
    """pyhwp 미설치 + (soffice 실패/부재) → 예외 없이 status='failed'."""
    raw = RawAttachment(file_name="규정.hwp", kind="hwp", content=b"not a real hwp")
    result = extract_attachment(raw)  # 예외가 나면 테스트 실패
    assert result.ocr_status == "failed"
    assert result.error_msg
    assert not result.extracted_text


def test_dispatch_pdf_scan_falls_back_to_ocr() -> None:
    """네이티브 텍스트 추출 불가(미설치/스캔) → 주입된 ocr_client 로 폴백."""
    raw = RawAttachment(file_name="스캔.pdf", kind="pdf", content=b"%PDF-1.4 no text layer")
    result = extract_attachment(raw, ocr_client=_ocr_client_returning("스캔본문"))
    assert result.method == "ocr-shim"
    assert result.ocr_status == "done"
    assert "스캔본문" in result.extracted_text


def test_dispatch_image_uses_ocr() -> None:
    raw = RawAttachment(file_name="표.png", kind="image", content=b"\x89PNG fake")
    result = extract_attachment(raw, ocr_client=_ocr_client_returning("이미지표"))
    assert result.method == "ocr-shim"
    assert "이미지표" in result.extracted_text


def test_dispatch_unsupported_kind_is_pending() -> None:
    raw = RawAttachment(file_name="문서.docx", kind="word", content=b"PK fake docx")
    result = extract_attachment(raw)
    assert result.ocr_status == "pending"
    assert not result.extracted_text


def test_dispatch_no_content_is_graceful() -> None:
    raw = RawAttachment(file_name="empty.pdf", kind="pdf", content=None)
    result = extract_attachment(raw)
    assert result.ocr_status in ("pending", "failed")
    assert not result.extracted_text
