"""PDF 추출 (plan §6): 네이티브 텍스트 레이어 우선, 텍스트 없으면 스캔판정 → OCR 위임.

``pypdf`` 는 선택 의존성(폐쇄망/미설치 가능) → **함수 내부 lazy import**. import 실패나 텍스트
미검출(스캔본)이면 주입된 ``OcrClient`` 로 폴백한다. OCR 클라이언트가 없으면 status='pending'
(추후 재처리 대상)으로 graceful degrade — 예외로 보드를 중단시키지 않는다(plan §8).
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from app.ingest.extract.ocr import extract_via_ocr
from app.ingest.models import ExtractResult

if TYPE_CHECKING:
    from app.ingest.extract.ocr import OcrClient

# 의미 있는 텍스트 레이어로 인정할 최소 글자 수(스캔본 오탐 방지).
_MIN_NATIVE_CHARS = 10


def _extract_native_text(content: bytes) -> str | None:
    """pypdf 로 텍스트 레이어 추출. 미설치/파싱오류/텍스트없음 → None(스캔 판정)."""
    try:
        from pypdf import PdfReader
    except Exception:
        return None
    try:
        reader = PdfReader(io.BytesIO(content))
        parts = [(page.extract_text() or "") for page in reader.pages]
    except Exception:
        return None
    text = "\n".join(p.strip() for p in parts if p.strip()).strip()
    if len(text) < _MIN_NATIVE_CHARS:
        return None
    return text


def extract_pdf(content: bytes, *, ocr_client: OcrClient | None = None) -> ExtractResult:
    """PDF 바이트 → ExtractResult. 네이티브 텍스트 우선, 없으면 OCR 폴백."""
    native = _extract_native_text(content)
    if native is not None:
        return ExtractResult(
            extracted_text=native,
            method="native",
            ocr_status="done",
        )
    if ocr_client is not None:
        return extract_via_ocr(content, ocr_client)
    return ExtractResult(
        method="native",
        ocr_status="pending",
        error_msg="텍스트 레이어 없음(스캔 추정) + OCR 클라이언트 미주입",
    )
