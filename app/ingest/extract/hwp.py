"""HWP/HWPX 추출 (plan §6): pyhwp 우선 → LibreOffice headless 폴백 → graceful failure.

- ``pyhwp`` 는 빌드 불안정(plan §11/§13) → **함수 내부 lazy import**, 부재 시 다음 폴백.
- LibreOffice 는 시스템 바이너리(``soffice --headless --convert-to txt``) → 파이썬 의존성 아님.
- 둘 다 불가하면 ``ExtractResult(ocr_status='failed', error_msg=...)`` 로만 떨어지고
  **예외를 던지지 않는다**(1글 실패가 보드 전체를 중단시키지 않음, plan §8).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from app.ingest.models import ExtractResult

_SOFFICE_TIMEOUT = 120


def _extract_with_pyhwp(content: bytes) -> str | None:
    """pyhwp(hwp5txt) 로 텍스트 추출. 미설치/실패 → None."""
    try:
        import hwp5  # noqa: F401  (설치 여부 확인용)
    except Exception:
        return None
    try:
        from hwp5.hwp5txt import TextTransform
        from hwp5.xmlmodel import Hwp5File
    except Exception:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.hwp"
        src.write_bytes(content)
        try:
            hwp = Hwp5File(str(src))
            transform = TextTransform()
            out = Path(tmp) / "out.txt"
            with out.open("w", encoding="utf-8") as fp:
                transform.transform_hwp5_to_text(hwp, fp)
            text = out.read_text(encoding="utf-8").strip()
        except Exception:
            return None
    return text or None


def _extract_with_libreoffice(content: bytes, suffix: str) -> str | None:
    """soffice --headless --convert-to txt 로 추출. 바이너리 부재/실패 → None."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{suffix}"
        src.write_bytes(content)
        try:
            proc = subprocess.run(
                [soffice, "--headless", "--convert-to", "txt:Text", "--outdir", tmp, str(src)],
                capture_output=True,
                timeout=_SOFFICE_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        out = Path(tmp) / "in.txt"
        if not out.exists():
            return None
        text = out.read_text(encoding="utf-8", errors="replace").strip()
    return text or None


def extract_hwp(content: bytes, *, file_name: str | None = None) -> ExtractResult:
    """HWP 바이트 → ExtractResult. pyhwp → LibreOffice → failed 순."""
    suffix = ".hwp"
    if file_name and "." in file_name:
        suffix = "." + file_name.rsplit(".", 1)[1].lower()

    text = _extract_with_pyhwp(content)
    if text:
        return ExtractResult(extracted_text=text, method="pyhwp", ocr_status="done")

    text = _extract_with_libreoffice(content, suffix)
    if text:
        return ExtractResult(extracted_text=text, method="libreoffice", ocr_status="done")

    return ExtractResult(
        ocr_status="failed",
        error_msg="HWP 추출 실패: pyhwp 미설치 + LibreOffice 변환 불가",
    )
