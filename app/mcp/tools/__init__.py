"""도구 7종 등록 — register_all(mcp) (Task009 plan §2).

각 도구 모듈의 register_* 를 호출해 FastMCP 에 도구를 등록하고 등록 개수를 반환한다(/healthz 보고).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.mcp.tools.aggregate import register_aggregate_compare
from app.mcp.tools.attachment import register_get_attachment
from app.mcp.tools.authority import register_get_approval_authority
from app.mcp.tools.board import register_list_boards
from app.mcp.tools.diff_tool import register_get_regulation_diff
from app.mcp.tools.regulation import register_get_regulation
from app.mcp.tools.search import register_search

_REGISTRARS = (
    register_search,
    register_get_regulation,
    register_get_attachment,
    register_list_boards,
    register_get_approval_authority,
    register_aggregate_compare,
    register_get_regulation_diff,
)


def register_all(mcp: FastMCP) -> int:
    """도구 7종을 등록하고 등록 개수를 반환한다."""
    for register in _REGISTRARS:
        register(mcp)
    return len(_REGISTRARS)
