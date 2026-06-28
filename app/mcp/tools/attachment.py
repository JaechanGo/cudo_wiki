"""get_attachment — 첨부 서빙 (Task009 plan §3.3, B-1).

text: download_url + redact_pii(추출텍스트), 바이트 미전송. image: B-1 게이트(큐레이션+볼륨) 충족
시에만 base64, 미충족(v1 기본)은 링크 폴백 + unverified_image 경고. ACL: post → board ∈ allowed.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP
from psycopg.rows import dict_row

from app.common.db import get_pool
from app.mcp import audit
from app.mcp.attachments import (
    encode_image_base64,
    is_curated_attachment,
    is_image_attachment,
    volume_available,
)
from app.mcp.context import Identity, resolve_identity
from app.mcp.redact_ext import redact_pii
from app.mcp.schemas import AttachmentOut
from app.mcp.tools._guard import ABSENT_MESSAGE_KO, DENY_MESSAGE_KO, gate_boards

_NOT_FOUND_KO = "해당 첨부를 찾을 수 없습니다."
_UNVERIFIED_IMAGE_KO = "미검증 이미지: 원문 확인 요망"


async def _load_ocr_text(conn, attachment_id: int, page_no: int | None) -> str | None:
    """attachment_page 의 OCR 텍스트(지정 page_no, 없으면 1p)를 가져온다."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT ocr_text FROM attachment_page "
            "WHERE attachment_id = %s AND page_no = %s",
            (attachment_id, page_no or 1),
        )
        row = await cur.fetchone()
    return row["ocr_text"] if row else None


async def _image_path(conn, attachment_id: int, page_no: int | None, storage_path: str) -> str:
    """image base64 원천 경로 — attachment_page.image_path 우선, 없으면 storage_path."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT image_path FROM attachment_page "
            "WHERE attachment_id = %s AND page_no = %s",
            (attachment_id, page_no or 1),
        )
        row = await cur.fetchone()
    if row and row["image_path"]:
        return row["image_path"]
    return storage_path


async def impl_get_attachment(
    conn,
    identity: Identity,
    *,
    attachment_id: int,
    page_no: int | None,
) -> AttachmentOut:
    """첨부 1건 서빙 — text 레닥션 / image B-1 게이트."""
    grant = await gate_boards(
        conn, identity, tool_name="get_attachment", requested=None
    )
    if grant is None:
        return AttachmentOut(message_ko=ABSENT_MESSAGE_KO)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT a.attachment_id, a.file_name, a.mime_type, a.kind, a.storage_path, "
            "a.download_url, a.extracted_text, a.is_table, a.byte_size, p.board_id "
            "FROM attachment a JOIN post p ON p.post_id = a.post_id "
            "WHERE a.attachment_id = %s",
            (attachment_id,),
        )
        att = await cur.fetchone()

    if att is None:
        return AttachmentOut(message_ko=_NOT_FOUND_KO)

    if att["board_id"] not in grant.allowed_boards:
        await audit.write_acl_audit(
            conn, tool_name="get_attachment", identity=identity, decision="deny",
            allowed=grant.allowed_boards, denied=[att["board_id"]],
            reason="board_not_allowed",
        )
        return AttachmentOut(message_ko=DENY_MESSAGE_KO)

    file_name = att["file_name"]
    mime_type = att["mime_type"]
    download_url = att["download_url"]

    # ── image 분기(B-1 게이트) ──────────────────────────────────────────
    if is_image_attachment(att["kind"], att["is_table"]):
        ocr_text = await _load_ocr_text(conn, attachment_id, page_no)
        ocr_text = redact_pii(ocr_text) if ocr_text else None

        image_b64: str | None = None
        # 게이트: 큐레이션 통과 AND 저장볼륨 마운트 둘 다 충족 시에만 base64.
        if await is_curated_attachment(conn, attachment_id):
            src_path = await _image_path(
                conn, attachment_id, page_no, att["storage_path"]
            )
            if volume_available(src_path):
                image_b64 = encode_image_base64(src_path)

        if image_b64 is None:
            # v1 기본 = 링크 폴백 + 경고(픽셀 PII 무노출 보장).
            return AttachmentOut(
                mode="image", file_name=file_name, mime_type=mime_type,
                page_no=page_no, image_base64=None, unverified_image=True,
                download_url=download_url, warning_ko=_UNVERIFIED_IMAGE_KO,
                ocr_text=ocr_text,
            )
        return AttachmentOut(
            mode="image", file_name=file_name, mime_type=mime_type, page_no=page_no,
            image_base64=image_b64, unverified_image=False, ocr_text=ocr_text,
        )

    # ── text 분기(v1 출시) ──────────────────────────────────────────────
    extracted = att["extracted_text"]
    return AttachmentOut(
        mode="text", file_name=file_name, mime_type=mime_type,
        download_url=download_url,
        text=redact_pii(extracted) if extracted else None,
    )


def register_get_attachment(mcp: FastMCP) -> None:
    """get_attachment 도구 등록."""

    @mcp.tool()
    async def get_attachment(
        attachment_id: int,
        ctx: Context,
        page_no: int | None = None,
    ) -> AttachmentOut:
        """첨부 서빙: text=링크+추출텍스트, image=큐레이션+볼륨 충족 시 base64(아니면 링크폴백)."""
        identity = resolve_identity(ctx)
        async with get_pool().connection() as conn:
            return await impl_get_attachment(
                conn, identity, attachment_id=attachment_id, page_no=page_no
            )
