#!/usr/bin/env bash
set -euo pipefail

REPO="noenemy/aiops-changemgmt"

# Scenario definitions: id|branch|title
SCENARIOS=(
  "l1|demo/i18n-messages|feat: API 응답 메시지 한국어 지원"
  "l2|demo/structured-logging|refactor: 구조화 로깅 적용 및 request_id 추가"
  "h1|demo/payment-integration|feat: 외부 결제 서비스 연동"
  "h2|demo/api-cleanup|refactor: API 응답 필드명 컨벤션 통일"
  "h3|demo/order-enrichment|feat: 주문 목록에 상품 상세 정보 포함"
  "h4|demo/checkout-feature|feat: 주문 생성 시 재고 차감 및 결제 처리"
)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

get_scenario() {
  local id="$1"
  for s in "${SCENARIOS[@]}"; do
    IFS='|' read -r sid sbranch stitle <<< "$s"
    if [[ "$sid" == "$id" ]]; then
      echo "$sid|$sbranch|$stitle"
      return 0
    fi
  done
  echo ""
  return 1
}

cmd_list() {
  echo ""
  printf "  ${BLUE}%-8s %-30s %-50s %s${NC}\n" "ID" "Branch" "Title" "Status"
  echo "  ─────────────────────────────────────────────────────────────────────────────────────────"

  for s in "${SCENARIOS[@]}"; do
    IFS='|' read -r sid sbranch stitle <<< "$s"

    # Check if there's an open PR for this branch
    pr_number=$(gh pr list --repo "$REPO" --head "$sbranch" --state open --json number --jq '.[0].number' 2>/dev/null || echo "")

    if [[ -n "$pr_number" ]]; then
      printf "  ${YELLOW}%-8s${NC} %-30s %-50s ${YELLOW}PR #%s open${NC}\n" "$sid" "$sbranch" "$stitle" "$pr_number"
    else
      printf "  ${GREEN}%-8s${NC} %-30s %-50s ${GREEN}ready${NC}\n" "$sid" "$sbranch" "$stitle"
    fi
  done
  echo ""
}

cmd_run() {
  local id="${1:-}"
  if [[ -z "$id" ]]; then
    echo -e "${RED}Usage: $0 run <scenario_id>${NC}"
    echo "  Available: l1, l2, h1, h2, h3, h4"
    exit 1
  fi

  local scenario
  scenario=$(get_scenario "$id") || {
    echo -e "${RED}Unknown scenario: $id${NC}"
    exit 1
  }
  IFS='|' read -r sid sbranch stitle <<< "$scenario"

  # Check if PR already exists
  existing=$(gh pr list --repo "$REPO" --head "$sbranch" --state open --json number --jq '.[0].number' 2>/dev/null || echo "")
  if [[ -n "$existing" ]]; then
    echo -e "${YELLOW}PR #${existing} already open for ${sbranch}. Reset first: $0 reset $id${NC}"
    exit 1
  fi

  echo -e "${BLUE}Creating PR for scenario: ${sid}${NC}"
  echo "  Branch: $sbranch"
  echo "  Title: $stitle"
  echo ""

  pr_url=$(gh pr create \
    --repo "$REPO" \
    --head "$sbranch" \
    --base main \
    --title "$stitle" \
    --body "$(cat <<EOF
## 변경 사항
데모 시나리오 $sid에 해당하는 코드 변경입니다.

> 이 PR은 AI Agent가 자동으로 분석합니다.
EOF
)" 2>&1)

  echo -e "${GREEN}✓ PR 생성 완료${NC}"
  echo "  $pr_url"
  echo ""
  echo -e "  ${BLUE}→ GitHub에서 PR을 확인하세요${NC}"
  echo -e "  ${BLUE}→ Slack #test-channel에서 분석 리포트를 확인하세요${NC}"
}

cmd_reset() {
  local id="${1:-}"
  if [[ -z "$id" ]]; then
    echo -e "${RED}Usage: $0 reset <scenario_id>${NC}"
    exit 1
  fi

  local scenario
  scenario=$(get_scenario "$id") || {
    echo -e "${RED}Unknown scenario: $id${NC}"
    exit 1
  }
  IFS='|' read -r sid sbranch stitle <<< "$scenario"

  pr_number=$(gh pr list --repo "$REPO" --head "$sbranch" --state open --json number --jq '.[0].number' 2>/dev/null || echo "")

  if [[ -z "$pr_number" ]]; then
    echo -e "${GREEN}No open PR for ${sbranch}. Already clean.${NC}"
    return
  fi

  gh pr close "$pr_number" --repo "$REPO" --comment "데모 리셋" 2>/dev/null
  echo -e "${GREEN}✓ PR #${pr_number} 닫힘. 시나리오 ${sid} 재시연 가능.${NC}"
}

cmd_reset_all() {
  echo -e "${YELLOW}Closing all open demo PRs...${NC}"
  for s in "${SCENARIOS[@]}"; do
    IFS='|' read -r sid sbranch stitle <<< "$s"
    pr_number=$(gh pr list --repo "$REPO" --head "$sbranch" --state open --json number --jq '.[0].number' 2>/dev/null || echo "")
    if [[ -n "$pr_number" ]]; then
      gh pr close "$pr_number" --repo "$REPO" --comment "데모 전체 리셋" 2>/dev/null
      echo -e "  ${GREEN}✓ ${sid}: PR #${pr_number} 닫힘${NC}"
    fi
  done
  echo -e "${GREEN}✓ 전체 리셋 완료${NC}"
}

cmd_help() {
  echo ""
  echo -e "${BLUE}AIOps Change Management Demo CLI${NC}"
  echo ""
  echo "Usage: $0 <command> [args]"
  echo ""
  echo "Commands:"
  echo "  list              모든 시나리오 상태 확인"
  echo "  run <id>          시나리오 PR 생성 (l1, l2, h1, h2, h3, h4)"
  echo "  reset <id>        시나리오 PR 닫기 (재시연 준비)"
  echo "  reset-all         모든 열린 PR 닫기"
  echo "  help              이 도움말 표시"
  echo ""
}

# Main
case "${1:-help}" in
  list)      cmd_list ;;
  run)       cmd_run "${2:-}" ;;
  reset)     cmd_reset "${2:-}" ;;
  reset-all) cmd_reset_all ;;
  help|*)    cmd_help ;;
esac
