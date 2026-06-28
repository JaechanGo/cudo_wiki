"""첨부 서빙 게이트 + 파일 IO (Task009 plan §3.3·§7.1, B-1).

text: download_url 링크 + redact_pii(추출텍스트) — C 가 바이트 미전송. v1 출시.
image: **B-1 게이트** — (큐레이션 통과 AND 저장볼륨 마운트) 둘 다 충족 시에만 base64. 미충족(=v1
기본, 볼륨 §9-3 미마운트)은 download_url 링크 폴백 + unverified_image 경고. 이미지 픽셀 PII 는
레닥션 불가 → 이 게이트로만 보호(NFR "무노출 0건").
"""

from __future__ import annotations

import base64
import os

# base64 서빙 크기 상한(인코딩 전 바이트 기준). 초과 시 링크 폴백(§3.3).
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# image 분기로 보내는 첨부 kind/특성.
_IMAGE_KINDS = {"image"}
# text 추출 서빙 대상 kind.
_TEXT_KINDS = {"hwp", "pdf", "word", "excel"}


def is_image_attachment(kind: str, is_table: bool) -> bool:
    """image 분기 대상인지 — kind='image' 또는 스캔/도표(is_table=true)."""
    return kind in _IMAGE_KINDS or bool(is_table)


def is_text_attachment(kind: str, is_table: bool) -> bool:
    """text 추출 서빙 대상인지 — hwp/pdf/word/excel 이며 표 이미지 아님."""
    return kind in _TEXT_KINDS and not is_table


async def is_curated_attachment(conn, attachment_id: int) -> bool:
    """첨부의 소속 post 가 큐레이션된 규정의 원천인지(B-1 게이트 조건 1).

    조인: attachment.post_id = regulation.source_post_id AND regulation.curated = true.
    (첨부 레벨 PII-clear 플래그는 스키마 부재 → 규정 단위 큐레이션이 v1 유일 PII-clear 신호.)
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT 1 FROM attachment a "
            "JOIN regulation r ON r.source_post_id = a.post_id AND r.curated "
            "WHERE a.attachment_id = %s LIMIT 1",
            (attachment_id,),
        )
        return (await cur.fetchone()) is not None


def volume_available(path: str | None) -> bool:
    """저장 볼륨 실파일이 mcp 컨테이너에서 읽히는지(B-1 게이트 조건 2). v1 미마운트 → False."""
    return bool(path) and os.path.isfile(path)


def encode_image_base64(path: str, *, max_bytes: int | None = None) -> str | None:
    """파일을 base64 로 인코딩. 부재/크기상한 초과/IO 실패 → None(링크 폴백).

    max_bytes 미지정 시 모듈 상한(MAX_IMAGE_BYTES)을 호출 시점에 읽는다(monkeypatch/설정 반영).
    """
    limit = MAX_IMAGE_BYTES if max_bytes is None else max_bytes
    try:
        size = os.path.getsize(path)
        if size > limit:
            return None
        with open(path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")
    except OSError:
        return None
