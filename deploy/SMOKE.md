# cudo-wiki ↔ LibreChat 연동 스모크 절차 (SMOKE.md)

> **이 문서는 절차서입니다.** Planner/실행자는 컨테이너를 **기동하지 않습니다**. 아래 "운영자
> 수동 적용"(§4)은 운영자가 책임지고 수행하는 단계입니다. 무기동 정적 검증(§2)·픽스처 경로
> 검증(§3)만 컨테이너 없이 로컬에서 수행 가능합니다.
>
> 진실원: C 구현(`app/mcp/*`) · 루트 `docker-compose.yml` · `.env.example` · 루트 `docker/Dockerfile.mcp`.

---

## 0. 전제 / 안전

- 운영 `/Users/.../librechat` 스택(`librechat.yaml`/`compose`/`.env`)은 **직접 수정·재기동 금지**.
  본 산출물은 운영자가 **수동 병합**할 추가분일 뿐입니다.
- `deploy/docker-compose.cudo-wiki.yaml` 의 외부망 2종(`librechat_default`,
  `litellm-gateway_default`)은 `external: true` — LibreChat / LiteLLM 스택이 **사전 생성**해야
  하며, 없으면 `up` 이 실패합니다.
- 호스트 포트는 전면 비노출입니다. 서버는 서비스명 DNS(`cudo-wiki-mcp:8080`)로만 도달하며,
  이것이 `app/mcp/server.py` 의 DNS rebinding 보호 비활성의 안전 전제입니다. **`ports:` 를
  추가하지 마세요.**
- 시크릿은 `../.env`(루트 `.env`)에만. 산출물 yaml 에 하드코딩 금지.

---

## 1. 산출물 목록

| 파일 | 용도 |
|---|---|
| `deploy/librechat.mcpServers.yaml` | 운영 librechat.yaml `mcpServers:` 에 병합할 `cudo-wiki` 스니펫 |
| `deploy/docker-compose.cudo-wiki.yaml` | `postgres`+`cudo-wiki-mcp`(+`migrate`) 배포 매니페스트 |
| `deploy/.env.example` | 얇은 포인터(루트 `.env.example` 가 SSOT) |
| `deploy/SMOKE.md` | 본 절차서 |
| `deploy/smoke.sh` | 무기동 정적 검증 스크립트(컨테이너 기동 안 함) |
| `deploy/RENDER_CONVENTIONS.md` | 출처/첨부/기권 렌더 규약 |

---

## 2. 무기동 정적 검증 (컨테이너 기동 없음 — 로컬/CI)

`deploy/smoke.sh` 가 아래를 자동화합니다(실패 시 비0 종료). 수동으로 확인하려면:

### 2.1 compose 정적 검증 (docker CLI 있을 때만)
```sh
docker compose -f deploy/docker-compose.cudo-wiki.yaml config
```
- 종료코드 0 기대. `env_file: required: false` 라 `../.env` 부재에도 통과합니다.
- 사전조건: Docker Compose v2.24+ (env_file long syntax `path:`/`required:` 키).
- docker CLI 가 없으면 이 단계는 건너뜁니다(치명 아님).

### 2.2 헤더 키 ↔ C 계약 대조
`deploy/librechat.mcpServers.yaml` 의 활성 `headers:` 3키가 C 상수와 일치해야 합니다.
진실원 `app/mcp/context.py`:
```
HEADER_ROLE    = "x-librechat-user-role"
HEADER_EMAIL   = "x-librechat-user-email"
HEADER_USER_ID = "x-librechat-user-id"
HEADER_SESSION = "x-librechat-session-id"   # yaml 에서는 주석(TODO §0/열린질문) — 활성 아님
```
- `{{LIBRECHAT_USER_ROLE/EMAIL/ID}}` 인증세션 보간만 사용. **customUserVars(`{{사용자입력}}`)
  미사용** 을 확인하세요(스푸핑 방지).

### 2.3 호스트 포트 미노출 확인
- `docker compose ... config` 출력(또는 두 compose 파일)에 `published`(호스트 매핑 ports)가
  **0건**이어야 합니다.

### 2.4 루트 compose 와 토폴로지 동치
- `deploy/docker-compose.cudo-wiki.yaml` 은 루트 `docker-compose.yml` 과 서비스/네트워크/이미지/
  볼륨/Dockerfile 이 동일하고, 경로만 `..` 재기준입니다. 둘 중 하나를 바꾸면 양쪽을 동기하세요.

---

## 3. 픽스처 기반 경로 검증 (무외부망, 로컬 pytest)

외부망/컨테이너 없이 C 순수 함수·핸들러 경로를 검증합니다.

### 3.1 샘플 규정 픽스처
`tests/fixtures/bizbox/1401000286/`(사내규정 보드):
```
board_p1.html      # 게시판 목록
post_1001.html  inner_1001.html   # 규정 게시글 본문
post_1002.html  inner_1002.html
authority.xlsx     # 전결권 표(get_approval_authority 용)
```

### 3.2 단위 테스트(외부 의존 없음)
```sh
pytest -m "not integration"
```
- 검색 전략·거절 게이트(`app/search/abstain.py`)·인용 후검증
  (`app/mcp/citations.py`)·ACL 게이트(`app/mcp/tools/_guard.py`) 순수 함수 그린 기대.

### 3.3 통합 경로(선택 — DB 필요)
`TEST_DATABASE_URL` 또는 testcontainers 로 PGroonga DB 를 띄우고 픽스처를 적재한 뒤:
- `impl_search_regulations(...)`(`app/mcp/tools/search.py`) 직접 호출
  → `SearchToolOut`(`abstained=false`, `hits[]`+`citations[]`+`hits[].source`) 확인.
- **무근거 질의**(코퍼스에 없는 주제) → `abstained=true` + `message_ko`
  (= `ABSTAIN_MESSAGE_KO`) 확인 → 기권 UX(FEAT-016) 신호.
- **신원부재**(헤더 빈값) → 도구가 `ABSENT_MESSAGE_KO` 표면화 + `acl_audit(identity_absent)`.

> 이 단계는 LibreChat·GLM 없이 C 경로만 검증합니다. End-to-end(챗→GLM→답변)는 §4 운영자 단계에서.

---

## 4. 운영자 수동 적용 단계 (컨테이너 기동 — 운영자 책임)

> ⚠️ 아래는 운영자가 운영 환경에서 수행합니다. 실행자/Planner 는 수행하지 않습니다.

1. **`.env` 준비**: 루트에서 `cp .env.example .env` 후 시크릿(DB_PASSWORD·LITELLM_KEY_GLM·
   BIZBOX_*) 채움. (deploy compose 는 `../.env` 참조.)
2. **스키마 적용(1회)**:
   ```sh
   docker compose -f deploy/docker-compose.cudo-wiki.yaml --profile migrate run --rm migrate
   ```
3. **기동**:
   ```sh
   docker compose -f deploy/docker-compose.cudo-wiki.yaml up -d postgres cudo-wiki-mcp
   ```
4. **헬스 확인**(컨테이너 내부/같은 망에서 — 호스트 비노출이므로 외부 curl 불가):
   - `GET /healthz` → `{"status":"ok","tools":7}`(DB 비의존, 도구 7종 보고).
   - `GET /readyz` → DB 도달 시 `{"status":"ready"}`, 실패 시 503.
5. **LibreChat 도달 확인**: LibreChat 컨테이너 내부에서
   ```sh
   curl http://cudo-wiki-mcp:8080/healthz
   ```
   (서비스명 DNS — 두 컨테이너가 `librechat_default` 망을 공유해야 함.)
6. **스니펫 병합**: `deploy/librechat.mcpServers.yaml` 의 `cudo-wiki:` 키를 운영 librechat.yaml
   `mcpServers:` 에 추가 → LibreChat 재기동(운영자 절차).
7. **챗 검증**: "연차휴가 며칠?" / "출장비 전결권자?" 류 질의 → 답변 하단에 출처(조항·시행일·
   원문링크) 표면화 확인(`RENDER_CONVENTIONS.md`). 근거 없는 질의 → 기권 메시지 확인.

---

## 5. 폐쇄망 도달성 체크리스트

- [ ] `cudo-wiki-mcp` 가 `librechat_default` 망에서 LibreChat 컨테이너에 서비스명
      DNS(`cudo-wiki-mcp:8080`)로 도달 가능.
- [ ] `cudo-wiki-mcp` → `litellm:4000`(litellm-gateway_default 망, GLM 리랭크 경유) 도달.
- [ ] `cudo-wiki-mcp` → `ocr-shim:8900`(OCR shim) 도달(첨부 OCR 경로 사용 시).
- [ ] **외부 egress 불필요**: GLM 은 LiteLLM 경유, 첨부는 사내 URL → 외부 인터넷 차단 환경에서
      전 경로 동작.
- [ ] 외부망 2종(`librechat_default`/`litellm-gateway_default`)이 **사전 존재**(external:true).
      없으면 `up` 실패 → LibreChat/LiteLLM 스택을 먼저 기동.
- [ ] 호스트 포트 0건(서비스명 DNS 로만 접근) — DNS rebinding 보호 비활성의 안전 전제 유지.

---

## 6. 미해결 / 후속 (plan §6)

- **session-id 헤더**(열린질문 #1): 네이티브 placeholder 부재 → yaml 에서 주석/TODO 비활성.
  `{{LIBRECHAT_BODY_conversationId}}` 활성 가부는 운영 연동 리콘 실테스트 필요. 비치명(nullable).
- **thumbs→query_log**(FEAT-018): v1 자동 배선 불가 → 범위 밖/후속. `RENDER_CONVENTIONS.md §4` 참조.
- **첨부 다운로드 URL 발급 주체**(FEAT-011): MCP 정적 서빙 vs 사이드카 미정 → 열린질문.
- **이미지 base64 인라인**: v1 기본 링크 폴백(볼륨 미마운트). 인라인 활성은 운영 결정 후속.
