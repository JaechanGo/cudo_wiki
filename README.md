# CUDO 사내 위키 (cudo_wiki)

쿠도커뮤니케이션(CUDO) 사내 규정·전결규정·공지·매뉴얼을 BizBox 그룹웨어에서
수집·분류·저장해 사내 위키를 만들고, LibreChat에 MCP로 연동하여
GLM-5.2가 사내 규정 질의에 답하도록 하는 시스템.

상태: **R0 — 프로젝트 스캐폴드 + DB 스키마(PostgreSQL + PGroonga)** 구현 단계.
설계 진실원은 `DESIGN.md` + `docs/design/erd.json`(13표/196컬럼).

## 구조

```
app/
  common/   # 설정(config) · DB 풀(db) · 로깅(logging)
  ingest/   # 서브시스템 A 인제스트·크롤 (R0 = 스텁)
  search/   # 서브시스템 B 검색 코어 (R0 = 스텁)
  mcp/      # 서브시스템 C MCP 서버 (R0 = streamable-http 골격 + /healthz, 도구 0개)
migrations/ # alembic (0001 확장 · 0002 13표 · 0003 인덱스)
docker/     # Dockerfile.mcp · postgres initdb 폴백
tests/      # unit(무DB) · integration(@integration, DB 필요시)
```

## 셋업 절차

> **사전조건**: Python ≥ 3.11, Docker, **Docker Compose v2.24+** (compose 의
> `env_file` long syntax `required:` 키가 v2.24.0(2024-01)부터 지원 — 구버전은
> `test_compose_config.py` 가 흔들릴 수 있음).

### 1) 환경변수
```bash
cp .env.example .env
# .env 를 열어 시크릿(DB_PASSWORD · LITELLM_KEY_GLM · BIZBOX_* 등) 채움.
# ★ .env 는 절대 커밋 금지(.gitignore 포함). .env.example 만 커밋.
```

### 2) 의존성 설치 (로컬 개발/테스트)
```bash
python3.11 -m venv .venv && source .venv/bin/activate   # 또는 python3.12
pip install -e ".[dev]"
```

### 3) DB 기동 (PGroonga)
```bash
docker compose up -d postgres        # internal 망 전용(호스트 포트 비노출)
```
> 외부망(`librechat_default` · `litellm-gateway_default`)은 `external: true` 이므로
> `cudo-wiki-mcp` 까지 `up` 하려면 LibreChat/LiteLLM 스택이 먼저 그 네트워크를 만들어야 함.
> 로컬 스키마 검증만 할 땐 `postgres` 만 단독 기동하면 충분.

### 4) 마이그레이션 (13표 생성)
```bash
# 방법 A) compose migrate 서비스(profile)
docker compose --profile migrate run --rm migrate

# 방법 B) 로컬에서 직접 (postgres 를 127.0.0.1 로 노출하는 override 필요)
#   ALEMBIC_DATABASE_URL 스킴은 반드시 postgresql+psycopg:// (psycopg3 강제)
ALEMBIC_DATABASE_URL=postgresql+psycopg://cudo:비밀@127.0.0.1:5432/cudo_wiki \
  alembic upgrade head

# 오프라인 SQL 미리보기(DB 연결 없이 DDL 확인)
alembic upgrade head --sql
```
> **[m-2] 마이그레이션 실행 롤 = DB 소유(superuser) 전제.** `pgroonga` 는 trusted
> extension 이 아니라 `CREATE EXTENSION` 에 superuser 권한이 필요. compose 의
> `POSTGRES_USER=${DB_USER}` 가 컨테이너 superuser 라 동작하나, 운영에서 비-superuser
> 롤로 마이그레이션하면 `0001_extensions` 가 실패함.
>
> downgrade 는 `alembic downgrade base` 로 0003(인덱스)→0002(테이블 CASCADE)→0001(확장) 역순.

### 5) 테스트
```bash
pytest -m "not integration"   # 단위(무DB) — 항상 그린
pytest -m integration         # 통합(DB 필요) — testcontainers 또는 TEST_DATABASE_URL
```
> 통합테스트는 `TEST_DATABASE_URL`/`DATABASE_URL` env 가 있으면 그 DB 를, 없으면
> `testcontainers` 로 `groonga/pgroonga` 컨테이너를 자동 기동(둘 다 없으면 skip).
> Docker Desktop(mac)에서 testcontainers 가 소켓을 못 찾으면
> `export DOCKER_HOST=unix://$HOME/.docker/run/docker.sock` 설정.

### 6) MCP 서버 기동
```bash
uvicorn app.mcp.server:app --host 0.0.0.0 --port 8080   # /healthz, /mcp(streamable-http)
```

## R0 범위 / 주의

- **임베딩(pgvector)은 phase-2 이연(ADR-002).** R0 스키마는 **13표 모두 생성**하되
  `chunk.embedding` 1컬럼만 미생성 → 전체 **195컬럼 = erd 196 − embedding 1**.
  이는 의도된 R0 deviation 이며 **결함이 아님**(`docs/design/erd.json` 의 196 과의 차이는
  embedding 1컬럼 뿐). phase-2 에서 `CREATE EXTENSION vector` + `ALTER TABLE chunk ADD
  COLUMN embedding vector(1024)` + 벡터 인덱스를 별도 마이그레이션으로 추가.
- **[M-2] `docker compose config` 는 `.env` 불요**(`env_file: required:false`),
  **런타임(`up` · `migrate`)은 `.env` 필수**(시크릿 미주입 시 실제 연결 실패).
- mecab 병렬은 방식 A(`chunk.tokenized` TokenDelimit, DB측 mecab 의존 0)만 R0 채택.
  방식 B(`clause.text` TokenMecab)는 이미지 mecab 사전 배포 구성이 필요해 후속.
- R0 는 외부망 실호출(BizBox 크롤 / GLM / OCR) 없음 — 골격만.
