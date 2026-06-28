"""attachments 파일 IO/게이트 단위테스트 (Task009 §3.3·§8.3 — DB 불필요).

base64 인코딩·크기상한·파일부재 폴백, image/text 분기 판정.
"""

from __future__ import annotations

import base64

from app.mcp.attachments import (
    encode_image_base64,
    is_image_attachment,
    is_text_attachment,
    volume_available,
)


def test_encode_existing_file(tmp_path):
    f = tmp_path / "img.png"
    f.write_bytes(b"PNGDATA")
    out = encode_image_base64(str(f))
    assert out == base64.b64encode(b"PNGDATA").decode("ascii")


def test_encode_missing_file_returns_none():
    assert encode_image_base64("/nonexistent/path/x.png") is None


def test_encode_size_limit_exceeded_returns_none(tmp_path):
    f = tmp_path / "big.png"
    f.write_bytes(b"x" * 100)
    assert encode_image_base64(str(f), max_bytes=10) is None


def test_volume_available_true_false(tmp_path):
    f = tmp_path / "v.png"
    f.write_bytes(b"y")
    assert volume_available(str(f)) is True
    assert volume_available("/nope/v.png") is False
    assert volume_available(None) is False


def test_is_image_attachment():
    assert is_image_attachment("image", False) is True
    assert is_image_attachment("pdf", True) is True  # 스캔/도표
    assert is_image_attachment("pdf", False) is False


def test_is_text_attachment():
    assert is_text_attachment("hwp", False) is True
    assert is_text_attachment("pdf", False) is True
    assert is_text_attachment("image", False) is False
    assert is_text_attachment("pdf", True) is False  # 표 이미지 → text 아님
