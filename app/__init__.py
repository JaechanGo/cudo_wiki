"""CUDO 사내 위키 — 패키지 루트.

서브시스템 레이아웃 (DESIGN §3, modular_monolith):
  app.ingest  — A 인제스트·크롤 (후속 태스크)
  app.search  — B 검색 코어 (후속 태스크)
  app.mcp     — C MCP 서버 (R0 = 기동 골격 + /healthz)
  app.common  — DB 풀 · 설정 · 로깅 (공용)
"""

__version__ = "0.1.0"
