"""MCP 프로토콜 경량 스모크 (Task009 §8.3·§8.4 — DB 불필요).

ASGI httpx 로 /healthz 200(도구 7개 보고) + /mcp initialize 수락 + tools/list 7개 확인. 전체 MCP
핸드셰이크 e2e 대신 경량 스모크 1건(M-1 import 회귀 가드 겸). lifespan 의 open_pool(wait=False)은
비차단이라 DB 없이도 startup 성공(/healthz·/mcp 는 DB 비의존).
"""

from __future__ import annotations

import json

import httpx

from app.mcp.server import app

_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _parse_sse(text: str) -> dict:
    """streamable-http 응답(SSE)에서 첫 data: JSON 을 파싱(일반 JSON 폴백)."""
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:"):].strip())
    return json.loads(text)


async def test_healthz_reports_seven_tools():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["tools"] == 7


async def test_mcp_initialize_and_tools_list():
    transport = httpx.ASGITransport(app=app)
    # FastAPI lifespan 수동 구동(session_manager.run + open_pool). DB 비의존.
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            init = await client.post(
                "/mcp/", headers=_MCP_HEADERS,
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "smoke", "version": "0"},
                    },
                },
            )
            assert init.status_code == 200
            session_id = init.headers.get("mcp-session-id")
            assert session_id, "initialize 가 세션 id 를 발급해야 함"
            init_data = _parse_sse(init.text)
            assert init_data["result"]["serverInfo"]["name"] == "cudo-wiki"

            await client.post(
                "/mcp/", headers={**_MCP_HEADERS, "mcp-session-id": session_id},
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )

            listed = await client.post(
                "/mcp/", headers={**_MCP_HEADERS, "mcp-session-id": session_id},
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
            assert listed.status_code == 200
            data = _parse_sse(listed.text)
            names = {t["name"] for t in data["result"]["tools"]}
            assert names == {
                "search_regulations", "get_regulation", "get_attachment",
                "list_boards", "get_approval_authority", "aggregate_compare",
                "get_regulation_diff",
            }, f"도구 7종 불일치: {names}"
