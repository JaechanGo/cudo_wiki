"""첨부 추출 dispatch (plan §6).

``extract_attachment`` 가 ``RawAttachment.kind`` 로 추출기를 선택한다:

| kind          | 추출기                   | method            |
|---------------|--------------------------|-------------------|
| excel         | excel.extract_excel_text | native (is_table) |
| hwp/hwpx      | hwp.extract_hwp          | pyhwp/libreoffice |
| pdf           | pdf.extract_pdf          | native → ocr-shim |
| image         | ocr.extract_via_ocr      | ocr-shim          |
| word/etc/그외 | (미지원)                 | — (pending)       |

추출 실패는 예외 대신 ``ExtractResult(ocr_status='failed'|'pending')`` 로 떨어진다(plan §8).
authority cells 산출(``extract_excel_cells``)은 run 오케스트레이션이 별도 호출(전결표 전용 경로).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.ingest.extract.excel import extract_excel_text
from app.ingest.extract.hwp import extract_hwp
from app.ingest.extract.ocr import extract_via_ocr
from app.ingest.extract.pdf import extract_pdf
from app.ingest.models import ExtractResult

if TYPE_CHECKING:
    from app.ingest.extract.ocr import OcrClient
    from app.ingest.models import RawAttachment

__all__ = ["extract_attachment"]


def extract_attachment(
    raw: RawAttachment, *, ocr_client: OcrClient | None = None
) -> ExtractResult:
    """첨부 1건 → ExtractResult. kind 판별 후 추출기 dispatch."""
    if not raw.content:
        return ExtractResult(ocr_status="pending", error_msg="첨부 바이트 없음")

    kind = (raw.kind or "").lower()
    if kind == "excel":
        text = extract_excel_text(raw.content)
        return ExtractResult(
            extracted_text=text or None,
            method="native",
            ocr_status="done",
            is_table=True,
        )
    if kind in ("hwp", "hwpx"):
        return extract_hwp(raw.content, file_name=raw.file_name)
    if kind == "pdf":
        return extract_pdf(raw.content, ocr_client=ocr_client)
    if kind == "image":
        if ocr_client is None:
            return ExtractResult(ocr_status="pending", error_msg="이미지 OCR 클라이언트 미주입")
        return extract_via_ocr(raw.content, ocr_client)

    # word/etc/미지원 — 추후 재처리 대상(pending).
    return ExtractResult(ocr_status="pending", error_msg=f"미지원 kind: {raw.kind}")
