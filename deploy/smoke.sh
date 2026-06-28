#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════
#  cudo-wiki deploy 스모크 — 무기동 정적 검증만.
# ════════════════════════════════════════════════════════════════════════════
#  ★ 이 스크립트는 컨테이너를 기동하지 않습니다.
#    `docker compose up`/`run`/`build`, 네트워크 호출(curl 등)을 일절 하지 않습니다.
#    수행하는 검사(전부 정적):
#      1) librechat.mcpServers.yaml / docker-compose.cudo-wiki.yaml YAML 파싱 유효성
#      2) librechat.mcpServers.yaml 활성 headers 3키 ↔ C app/mcp/context.py 상수 대조
#      3) customUserVars 미사용 확인
#      4) 호스트 포트 미노출 확인(두 yaml 에 published ports 패턴 0건)
#      5) (docker CLI 있을 때만) `docker compose ... config` 종료0 — 무기동 정적 검증
#    컨테이너 기동/스키마 적용/챗 검증은 SMOKE.md §4 운영자 수동 단계 참조.
#
#  사용: bash deploy/smoke.sh   (worktree 루트에서 실행 권장)
#  종료코드: 0=통과, 1=실패. docker CLI 부재는 경고일 뿐 실패 아님.
# ════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# 스크립트 위치 기준으로 deploy/ 와 worktree 루트 산출 — 어디서 실행해도 동작.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
MCP_YAML="${SCRIPT_DIR}/librechat.mcpServers.yaml"
COMPOSE_YAML="${SCRIPT_DIR}/docker-compose.cudo-wiki.yaml"
CONTEXT_PY="${ROOT_DIR}/app/mcp/context.py"

fail=0
note() { printf '  %s\n' "$*"; }
ok()   { printf '[ OK ] %s\n' "$*"; }
bad()  { printf '[FAIL] %s\n' "$*"; fail=1; }
warn() { printf '[WARN] %s\n' "$*"; }

# ── 1. YAML 파싱 유효성 ──────────────────────────────────────────────────────
echo "== 1. YAML 파싱 유효성 =="
if command -v python3 >/dev/null 2>&1; then
  for y in "${MCP_YAML}" "${COMPOSE_YAML}"; do
    if python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" "${y}" 2>/dev/null; then
      ok "YAML 유효: $(basename "${y}")"
    else
      bad "YAML 파싱 실패: $(basename "${y}")"
    fi
  done
else
  warn "python3 부재 — YAML 파싱 검증 건너뜀(치명 아님)."
fi

# ── 2. 헤더 키 ↔ C 상수 대조 ─────────────────────────────────────────────────
echo "== 2. 헤더 키 ↔ C context.py 대조 =="
# yaml 의 '활성'(주석 아님) 헤더 줄만 추출. session-id 는 yaml 에서 주석이어야 함.
for key in x-librechat-user-role x-librechat-user-email x-librechat-user-id; do
  if grep -Eq "^[[:space:]]*${key}:" "${MCP_YAML}"; then
    if grep -q "\"${key}\"" "${CONTEXT_PY}"; then
      ok "헤더 키 일치(yaml 활성 ↔ C 상수): ${key}"
    else
      bad "헤더 키가 C context.py 에 없음: ${key}"
    fi
  else
    bad "yaml 에 활성 헤더 누락: ${key}"
  fi
done
# session-id 는 yaml 에서 비활성(주석)이어야 함 — 활성으로 박혀 있으면 경고.
if grep -Eq "^[[:space:]]*x-librechat-session-id:" "${MCP_YAML}"; then
  warn "x-librechat-session-id 가 활성 상태 — 네이티브 placeholder 부재(SMOKE.md §0). 의도 확인."
else
  ok "session-id 헤더 비활성(주석) — 의도대로(존재하지 않는 placeholder 미사용)."
fi

# ── 3. customUserVars 미사용 ─────────────────────────────────────────────────
echo "== 3. customUserVars 미사용 =="
# 주석(# ...) 줄을 제거한 뒤 실제 사용(키/값)만 탐지 — 설명 주석의 'customUserVars 금지'는 무시.
if sed 's/#.*$//' "${MCP_YAML}" | grep -q "customUserVars"; then
  bad "librechat.mcpServers.yaml 에 customUserVars 사용 발견 — 스푸핑 위험, 제거 필요."
else
  ok "customUserVars 미사용(인증세션 보간만; 주석 설명은 무시)."
fi

# ── 4. 호스트 포트 미노출 ────────────────────────────────────────────────────
echo "== 4. 호스트 포트 미노출 =="
# 활성(주석 아님) 'ports:' 매핑이 있으면 실패. (url: 의 :8080 은 포트 매핑이 아니므로 무관.)
if grep -Eq "^[[:space:]]*ports:" "${COMPOSE_YAML}"; then
  bad "docker-compose.cudo-wiki.yaml 에 활성 ports: 발견 — 호스트 포트 비노출 위반."
else
  ok "compose 에 활성 ports: 0건(호스트 포트 비노출)."
fi

# ── 5. docker compose config (있을 때만, 무기동) ─────────────────────────────
echo "== 5. docker compose config (정적, 무기동) =="
if command -v docker >/dev/null 2>&1; then
  if docker compose -f "${COMPOSE_YAML}" config >/dev/null 2>&1; then
    ok "docker compose config 종료0(정적 검증 통과)."
  else
    bad "docker compose config 실패 — 출력 확인: docker compose -f ${COMPOSE_YAML} config"
  fi
else
  warn "docker CLI 부재 — compose config 건너뜀(치명 아님). SMOKE.md §2.1 수동 검증."
fi

echo
if [ "${fail}" -eq 0 ]; then
  echo "==> 정적 스모크 통과. (컨테이너 기동/E2E 는 SMOKE.md §4 운영자 단계.)"
  exit 0
else
  echo "==> 정적 스모크 실패 — 위 [FAIL] 항목 수정 필요."
  exit 1
fi
