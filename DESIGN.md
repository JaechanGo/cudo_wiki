# CUDO 사내 위키 — 구현 설계 (DESIGN)

> 설계 진실원: LogiCraft 프로젝트 **cudo-wiki** (`eac9ec3c-4b4f-4bd4-ab5c-b968eba7658b`).
> 전체 ITEM(FEAT 36 · ADR 4 · ERD-001 · NFR 5 · RISK 7 · EXTSYS/INT 4)은 LogiCraft MCP 로 조회 가능하면 그쪽이 우선. 이 문서는 컨덕터용 단일 요약 + 오프라인 진실원.
> 전체 ERD(13표/196컬럼) JSON: `docs/design/erd.json` (= LogiCraft ERD-001).

## 0. 한 줄
직원이 한국어로 사내 규정/전결규정/공지/매뉴얼을 질문 → LibreChat 의 GLM-5.2 가 위키 근거(조항)+첨부 원문 링크와 함께 답하는 **온프렘 RAG**. 크롤은 **정기 배치(증분)**, 질의는 **저장된 DB 검색**(라이브 크롤 아님).

## 1. 기술 스택 (확정)
- 백엔드: **Python / FastAPI**
- DB: **PostgreSQL + PGroonga**(한국어 FTS). phase-2: pgvector.
- MCP 서버: **Python MCP SDK**, transport=**streamable-http**
- 컨테이너: docker-compose (기존 librechat 스택에 합류)
- 마이그레이션: alembic (13표 스키마)
- 문서 추출: pyhwp + LibreOffice headless(HWP/HWPX), ocr-shim(스캔 PDF/이미지), openpyxl(xlsx 수당표)
- LLM: GLM-5.2 (OpenAI 호환) — **사내 LiteLLM 경유**

## 2. 배포 배선 (리콘 005 확정)
- 도커 네트워크: **`librechat_default`** (필수) + **`litellm-gateway_default`** (GLM 경유용)
- GLM: **`http://litellm:4000/v1`** (외부 NHN 직결은 현재 TLS 다운 → LiteLLM 경유) → **ADR-005**(추론모델 대응) 참조
- OCR: **`http://ocr-shim:8900`** (`POST /v1/ocr`, body `{document:{document_url:"data:application/pdf;base64,.."}}` → `pages[].markdown`)
- `cudo-wiki-mcp`: 호스트 포트 비노출(서비스명 DNS만), nginx 불필요
- `librechat.yaml`: `mcpServers` 섹션 **신규 추가** (`type: streamable-http`, `url: http://cudo-wiki-mcp:<PORT>/mcp`, `serverInstructions: true`)
- 사용자 신원: **`{{LIBRECHAT_USER_ROLE/EMAIL}}` 헤더 보간**(인증세션 주입, customUserVars 아님) → ACL 입력
- 시크릿: GLM/LiteLLM 키는 `.env`(`LITELLM_KEY_GLM` 등), BizBox 서비스계정 비번도 `.env`. **코드 하드코딩 금지**.

## 3. 컨벤션
- **modular_monolith**. 내부 호출 = 단일 프로세스 함수/SQL (마이크로서비스 HTTP 아님). 설계의 `/internal/*` 는 내부 모듈 인터페이스 의미.
- 리포 레이아웃(제안): `app/ingest/` · `app/search/` · `app/mcp/` · `app/common/`(db·config) · `migrations/` · `docker/` · `tests/`
- 한국어 정규화: 원문자 ①②③·전각숫자 → 정규 조항 ID, EUC-KR/HTML 모지바케 정제
- 인용은 **메타데이터 결정론**(LLM 이 조번호 생성 금지)
- 모든 사용자 노출 텍스트 한국어. 테스트 필수(검색·인용·거절·ACL).

## 4. 4개 서브시스템 + FEAT (LogiCraft 에서 상세 조회)
### A 인제스트·크롤 (DOMAIN-001) — FEAT-009·015·022·026·031·034·035·036
BizBox 세션 크롤러(증분: artNo/등록일 델타·멱등 upsert), HWP/OCR/xlsx 첨부 추출, HTML·인코딩 정제, 본문 정규화·결정론 메타, **인간검증 큐레이션 큐(curation_queue)**, **헬스 모니터링(must)**, 큐레이션 백업/export.

### B 검색 코어 (DOMAIN-002) — FEAT-002·004·006·008·012·021·024·028·029
PGroonga 인덱싱(N-gram + 규정/전결 보드 mecab 병렬 + 사용자사전 + 조항ID 정확필드), 조(Article) 단위 청킹+시행일 버전, **전결표 구조화(금액 numrange → SQL 범위필터)**, 동의어·mecab 사전, **GLM 리랭크(레닥션본 전송)**, **인용 결정론+근거없으면 거절**, 집계·비교·카운트, 질의 intent 분류, **평가 하네스+골든셋(must)**.

### C MCP 서버 (DOMAIN-003) — FEAT-010·014·017·019·020·025·027·030·032·033 + API-001~007
streamable-http 런타임. 도구 7: `search_regulations` · `get_regulation` · `get_attachment` · `list_boards` · `get_approval_authority` · `aggregate_compare` · `get_regulation_diff`. 인용 검증, **ACL(헤더 신원 기반 보드 접근제어)**, **PII 레닥션(PIPA)**, 첨부 서빙(text 다운로드 링크 + image base64).

### D LibreChat 연동 (DOMAIN-004) — FEAT-001·003·005·007·011·013·016·018
`librechat.yaml` mcpServers 등록, docker-compose 배선(librechat_default + litellm-gateway_default), 신원 헤더 보간→ACL, GLM 답변에 **출처(조항) 인용 렌더**, 첨부 링크·이미지, GLM 엔드포인트 바인딩, **thumbs 피드백→query_log**, 기권 UX, 폐쇄망 스모크.

## 5. 핵심 결정 (ADR)
- **ADR-001** 검색엔진 = 단일 Postgres+PGroonga 렉시컬-우선 (임베딩 phase-2)
- **ADR-002** 임베딩 v1 없음, phase-2 가산 (트리거: recall@10 < 85%), KURE-v1/bge-m3
- **ADR-003** 인제스트 2단: 핵심(106 규정 + 전결표 + 핵심 별표) **인간검증 큐레이션**, 나머지 자동
- **ADR-004** 인용 = 메타데이터 결정론 + 거절게이트, **ACL v1 = 전직원 19보드(헤더 신원)**
- **ADR-005** GLM-5.2 는 **추론(reasoning) 모델** — 응답이 `content`+`reasoning_content` 로 분리. 추론이 `max_tokens` 를 잠식하면 `content=''`(finish=length)로 빈 답이 됨. **대응**: ① **리랭크(B/C)** = `app/search/glm_client.py` payload 에 `chat_template_kwargs:{enable_thinking:false}` + 넉넉한 `max_tokens`(512). `reasoning_effort:low`(역효과)·`thinking:{type:disabled}`(무시) 는 미작동 → 채택 금지. ② **답변생성(D)** = 운영 `librechat.yaml` endpoint 모델 설정에 동일 이슈 존재 → 넉넉한 `max_tokens`(또는 LiteLLM 모델 params 로 `enable_thinking:false`)로 **답변 잘림 방지**(운영 endpoint 영역 = D 코드범위 밖 → `deploy/SMOKE.md §4/§6`·`deploy/RENDER_CONVENTIONS.md §1.6` 에 운영자 지침). 엔드포인트는 LiteLLM 경유, 인증 `Authorization: Bearer`.

## 6. 품질기준 / 위험
- **NFR**: 인용정확도 ≥98% · 기권 ≥95% · ACL/PII 무노출 =0건 · recall@10 ≥85% · 신선도 ≤24h
- **RISK**(완화책은 LogiCraft RISK-001~007): HWP추출 노이즈 · 전결표 2D · 동의어 register 불일치 · 크롤 무신호 중단 · 평가 부재 · 환각/충실도 · PII 노출

## 7. 데이터 원천 — BizBox 크롤 계약
- `http://gw.cudo.co.kr/gw/bizbox.do` (세션쿠키 JSESSIONID, Java/EDMS). 셸 bizbox.do → iframe `_content` EDMS.
- 목록: `GET /edms/board/viewBoard.do?boardNo=&currentPage=&countPerPage=` → HTML 표(번호·제목·작성자·조회·좋아요·등록일), 글은 `viewPost(artNo)`
- 글: `GET /edms/board/viewPost.do?boardNo=&artNo=` → 메타 + 본문(**nested iframe `bizboxLink.do?url=<urlenc /edms/..>` 2-hop**)
- 첨부 다운로드: `/gw/cmm/file/edmsDownloadProc.do`(메인) · `/edms/board/downloadFile.do` · `/edms/doc/downloadFile.do`. 파일필드 `fileNm/fileRnm/filePath/saveFileName/orignlFileName/fileExt`
- 인증(라이브 실측 2026-06-29 — 구현·검증 `app/ingest/bizbox_client.py:login()`): **eGov + Spring Security 3단계, AES 암호화**.
  ① GET `/gw/uat/uia/egovLoginUsr.do`(세션·anti-bot) → ② POST `/gw/uat/uia/actionLogin.do`(id/password 를 `securityEncrypt()`=AES-128-CBC-PKCS7+base64+`'!'`+encodeURIComponent, 정적키=iv `jIBQW9QlRqV#DT(C`, Referer 필수; 암호화 id 50자 초과 시 id/id_sub1/id_sub2 분할) → Spring Security 자동제출 폼 응답 → ③ POST `/gw/j_spring_security_check`(폼의 j_username/j_password) → 인증 세션. 자격은 .env.
- ⚠️ **boardNo ≠ jstree 노드 id**: 트리 노드 id `1401000286`(사내규정)의 실제 boardNo = **`900000286`**(뒤 6자리 일치). §위 19보드 표는 jstree id → 실제 boardNo 매핑 필요(포털/트리 데이터에서 확정).
- ⚠️ **글 목록은 AJAX 로드**: `viewBoard.do` 응답은 셸(검색폼·좌측트리·페이징 컨테이너, `totalCount`=106 만 포함)이고 `<table>`/`<tr>` 행 아님. 실제 글 행은 **별도 AJAX 엔드포인트**가 반환 → 현재 목 fixture 기반 `<tr>` 파서(`crawler._parse_list_rows`) 미작동, list/post/body/첨부 파싱을 라이브 구조로 재작성 필요. 증분: artNo/등록일.

### 수집 대상 19개 보드 (사내게시판, boardNo=jstree node id)
| boardNo | 게시판 | 비고 |
|---|---|---|
| 501000073 | CEO칼럼 | |
| 501000074 | 공지사항 | 최다(986) |
| 1401000409 | 쿠도제안게시판 | |
| 1401000286 | **사내규정** | 규정 핵심(106) |
| 1401000327 | 사내양식함 | |
| 1401000325 | 뉴스클리핑 | 외부기사 저작권 주의(내부참고만) |
| 1401000306 | 월례회의자료 | |
| 1401000070 | 독서게시판 | |
| 1401000326 | 회사소개서 | |
| 1401000439 | 외국어 신청 | |
| 1401000575 | ERP 설치 매뉴얼 | |
| 1401000577 | ERP 사용 매뉴얼 | |
| 1401000578 | ERP 인사평가 매뉴얼 | |
| 1401000606 | ERP 사용자 교육 | |
| 1401000605 | 그룹웨어 매뉴얼/OJT | |
| 1401000668 | 화상회의 매뉴얼 | |
| 1401000669 | 자격증 축하금 LIST | |
| 1401000679 | 버크만진단 참고자료 | |
| 1401000704 | 임직원 교육·설문결과 | |

**제외(개인정보 4개)**: 1401000141 인사발령 · 501000075 경조사 · 1401000440 모범사원 · 1401000711 CUDO동호회.

## 8. 범위 밖 / 추후 확정
- phase-2: 임베딩/벡터검색(pgvector+KURE-v1), 보드별 직무 게이팅 ACL
- 운영 합의 필요(구현 중 확정): `canonical_clause_id` 명명규칙, `reg_code` 체계, 수집 주기, mecab 사전 운영주체
