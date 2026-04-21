// Demo scenario definitions — shared by UI (description panel, terminal
// playback script, architecture diagram highlights, and the mock Slack
// preview). Keep one scenario object self-contained so editors can tweak
// any single scenario without touching the rest of the app.

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type Verdict = "APPROVE" | "REJECT";
export type ChangeType = "code" | "iac" | "mixed";

export type TerminalLine =
  | { kind: "prompt"; text: string; delayMs?: number }
  | { kind: "stdout"; text: string; delayMs?: number }
  | { kind: "stderr"; text: string; delayMs?: number }
  | { kind: "info"; text: string; delayMs?: number }
  | { kind: "success"; text: string; delayMs?: number }
  | { kind: "warn"; text: string; delayMs?: number }
  | { kind: "wait"; label: string; durationMs: number };

export type HighlightedNode =
  | "github"
  | "webhook"
  | "analysis"
  | "runtime"
  | "gateway"
  | "pr_tools"
  | "kb_tools"
  | "ddb_tools"
  | "slack_tools"
  | "memory"
  | "kb"
  | "slack";

export interface SlackPreview {
  pr_number: number;
  pr_title: string;
  pr_author: string;
  pr_url: string;
  change_type: ChangeType;
  risk_score: number;
  risk_level: Severity;
  verdict: Verdict;
  summary: string;
  issues_text?: string;
  incident_match?: string;
  developer_pattern?: string;
  infra_impact?: string;
  agent_persona: string;
}

export interface Scenario {
  id: string;
  label: string;
  title: string;
  severity: Severity;
  expectedVerdict: Verdict;
  branch: string;
  changedFile: string;
  problem: string;
  expectedKbMatch?: string;
  // A-mode: narrative terminal script
  terminal: TerminalLine[];
  // C-mode: actual shell command to run (via API route). Kept explicit
  // so we never execute anything beyond the allowlist.
  liveCommand: {
    cmd: string;
    args: string[];
    cwd?: string;
    // Approx wall time. Used to show progress bar; not a hard timeout.
    expectedSeconds: number;
  };
  highlightPath: HighlightedNode[];
  slackPreview: SlackPreview;
}

// Base URL assumes the real demo repo; override via env if someone forks.
const REPO = "noenemy/aiops-changemgmt";
const prUrl = (n: number) => `https://github.com/${REPO}/pull/${n}`;

const commonFooter: TerminalLine[] = [
  { kind: "info", text: "→ Runtime 응답 수신", delayMs: 400 },
  { kind: "success", text: "✓ GitHub PR 코멘트 작성 완료" },
  { kind: "success", text: "✓ Slack 리포트 전송 완료" },
  { kind: "stdout", text: "" },
];

export const scenarios: Scenario[] = [
  // ──────────────────────────────────────────────────────────────────────
  {
    id: "l1",
    label: "L1 · i18n",
    title: "API 응답 메시지 한국어 지원",
    severity: "LOW",
    expectedVerdict: "APPROVE",
    branch: "demo/i18n-messages",
    changedFile: "sample-app/src/handlers/messages.py",
    problem:
      "응답 메시지를 영어에서 한국어로 변경하는 단순 리소스 변경. 로직 변화 없음.",
    terminal: [
      { kind: "prompt", text: "$ ./demo.sh run l1" },
      { kind: "stdout", text: "Creating PR for scenario: l1" },
      { kind: "stdout", text: "  Branch: demo/i18n-messages" },
      { kind: "stdout", text: "  Title:  feat: API 응답 메시지 한국어 지원" },
      { kind: "success", text: "✓ PR #11 생성" },
      { kind: "info", text: "→ GitHub Webhook 수신, Runtime 호출 중..." },
      {
        kind: "wait",
        label: "detect_change_type → get_pr_diff → CodeReviewer → RiskJudge",
        durationMs: 3500,
      },
      { kind: "stdout", text: "  🟢 Risk Score: 8/100 (LOW)" },
      { kind: "stdout", text: "  판정: ✅ APPROVE" },
      ...commonFooter,
    ],
    liveCommand: {
      cmd: "./demo.sh",
      args: ["run", "l1"],
      expectedSeconds: 95,
    },
    highlightPath: ["github", "webhook", "analysis", "runtime", "pr_tools", "slack_tools", "slack"],
    slackPreview: {
      pr_number: 11,
      pr_title: "feat: API 응답 메시지 한국어 지원",
      pr_author: "dev-ethan",
      pr_url: prUrl(11),
      change_type: "code",
      risk_score: 8,
      risk_level: "LOW",
      verdict: "APPROVE",
      summary:
        "사용자 대면 응답 메시지를 한국어로 변경. 비즈니스 로직 변화 없음.",
      agent_persona: "RiskJudge",
    },
  },
  // ──────────────────────────────────────────────────────────────────────
  {
    id: "l2",
    label: "L2 · 로깅",
    title: "구조화 로깅 적용 및 request_id 추가",
    severity: "LOW",
    expectedVerdict: "APPROVE",
    branch: "demo/structured-logging",
    changedFile: "sample-app/src/handlers/*.py",
    problem: "전체 핸들러에 JSON 구조화 로그 + request_id 추가. 관측성 개선.",
    terminal: [
      { kind: "prompt", text: "$ ./demo.sh run l2" },
      { kind: "stdout", text: "Creating PR for scenario: l2" },
      { kind: "stdout", text: "  Branch: demo/structured-logging" },
      { kind: "success", text: "✓ PR #12 생성" },
      { kind: "info", text: "→ Runtime 분석 중..." },
      {
        kind: "wait",
        label: "CodeReviewer: 로깅 패턴 검토 + KB 정책 조회",
        durationMs: 3500,
      },
      { kind: "stdout", text: "  🟢 Risk Score: 12/100 (LOW)" },
      { kind: "stdout", text: "  판정: ✅ APPROVE" },
      ...commonFooter,
    ],
    liveCommand: { cmd: "./demo.sh", args: ["run", "l2"], expectedSeconds: 95 },
    highlightPath: [
      "github",
      "webhook",
      "analysis",
      "runtime",
      "pr_tools",
      "kb_tools",
      "slack_tools",
      "slack",
    ],
    slackPreview: {
      pr_number: 12,
      pr_title: "refactor: 구조화 로깅 적용 및 request_id 추가",
      pr_author: "dev-ethan",
      pr_url: prUrl(12),
      change_type: "code",
      risk_score: 12,
      risk_level: "LOW",
      verdict: "APPROVE",
      summary:
        "모든 Lambda 핸들러에 JSON 로그와 request_id 전파 추가. 관측성 개선.",
      agent_persona: "RiskJudge",
    },
  },
  // ──────────────────────────────────────────────────────────────────────
  {
    id: "h1",
    label: "H1 · 시크릿 유출",
    title: "외부 결제 서비스 연동",
    severity: "CRITICAL",
    expectedVerdict: "REJECT",
    branch: "demo/payment-integration",
    changedFile: "sample-app/src/handlers/create_order.py",
    problem:
      "결제 API 키가 코드에 하드코딩됨. GitHub 저장소에 그대로 커밋되면 시크릿 유출.",
    expectedKbMatch: "INC-0045",
    terminal: [
      { kind: "prompt", text: "$ ./demo.sh run h1" },
      { kind: "success", text: "✓ PR #13 생성" },
      { kind: "info", text: "→ Runtime 분석 중..." },
      {
        kind: "wait",
        label: "CodeReviewer → invoke_security_agent → KB incidents 조회",
        durationMs: 5000,
      },
      { kind: "warn", text: "  ⚠ 하드코딩된 API 키 패턴 감지" },
      { kind: "warn", text: "  ⚠ INC-0045 (시크릿 유출, 2025-12-08) 매칭" },
      { kind: "stderr", text: "  🔴 Risk Score: 95/100 (CRITICAL)" },
      { kind: "stderr", text: "  판정: 🚫 REJECT — CI/CD 파이프라인 차단" },
      ...commonFooter,
    ],
    liveCommand: { cmd: "./demo.sh", args: ["run", "h1"], expectedSeconds: 110 },
    highlightPath: [
      "github",
      "webhook",
      "analysis",
      "runtime",
      "pr_tools",
      "kb_tools",
      "kb",
      "slack_tools",
      "slack",
    ],
    slackPreview: {
      pr_number: 13,
      pr_title: "feat: 외부 결제 서비스 연동",
      pr_author: "dev-ethan",
      pr_url: prUrl(13),
      change_type: "code",
      risk_score: 95,
      risk_level: "CRITICAL",
      verdict: "REJECT",
      summary:
        "결제 API 키가 소스 코드에 하드코딩되어 있음. Secrets Manager로 이전 필수.",
      issues_text:
        "• 🔴 CRITICAL · `create_order.py:24` — API 키 하드코딩\n• 🟡 HIGH · 에러 응답에 원본 예외 메시지 노출",
      incident_match:
        "`INC-0045` (2025-12-08) — 동일 패턴으로 토큰이 퍼블릭 저장소에 노출되어 48시간 대응 발생",
      developer_pattern:
        "이전 PR #7에서도 환경변수 미사용 패턴이 있었음 (재발)",
      agent_persona: "RiskJudge",
    },
  },
  // ──────────────────────────────────────────────────────────────────────
  {
    id: "h2",
    label: "H2 · Breaking API",
    title: "API 응답 필드명 컨벤션 통일",
    severity: "HIGH",
    expectedVerdict: "REJECT",
    branch: "demo/api-cleanup",
    changedFile: "sample-app/src/handlers/get_orders.py",
    problem:
      "응답 필드명을 snake_case로 바꾸면서 기존 클라이언트 호환성을 깨뜨림.",
    expectedKbMatch: "INC-0038",
    terminal: [
      { kind: "prompt", text: "$ ./demo.sh run h2" },
      { kind: "success", text: "✓ PR #14 생성" },
      { kind: "info", text: "→ Runtime 분석 중..." },
      {
        kind: "wait",
        label: "CodeReviewer → KB runbooks(api-change-policy) 조회",
        durationMs: 4500,
      },
      { kind: "warn", text: "  ⚠ Breaking API Change — 필드명 변경" },
      { kind: "warn", text: "  ⚠ INC-0038 패턴 매칭 (2025-10-22)" },
      { kind: "stderr", text: "  🔴 Risk Score: 72/100 (HIGH)" },
      { kind: "stderr", text: "  판정: 🚫 REJECT" },
      ...commonFooter,
    ],
    liveCommand: { cmd: "./demo.sh", args: ["run", "h2"], expectedSeconds: 105 },
    highlightPath: [
      "github",
      "webhook",
      "analysis",
      "runtime",
      "pr_tools",
      "kb_tools",
      "kb",
      "slack_tools",
      "slack",
    ],
    slackPreview: {
      pr_number: 14,
      pr_title: "refactor: API 응답 필드명 컨벤션 통일",
      pr_author: "dev-jinwoo",
      pr_url: prUrl(14),
      change_type: "code",
      risk_score: 72,
      risk_level: "HIGH",
      verdict: "REJECT",
      summary:
        "`orderId` → `order_id` 등 응답 필드명 변경. 기존 모바일 클라이언트 호환성 파괴.",
      issues_text:
        "• 🔴 HIGH · `get_orders.py` — 응답 스키마 Breaking Change\n• 🟡 MEDIUM · 마이그레이션 플래그/버전 분기 없음",
      incident_match:
        "`INC-0038` (2025-10-22) — 유사한 응답 필드 변경으로 모바일 앱 크래시",
      agent_persona: "RiskJudge",
    },
  },
  // ──────────────────────────────────────────────────────────────────────
  {
    id: "h3",
    label: "H3 · N+1 쿼리",
    title: "주문 목록에 상품 상세 정보 포함",
    severity: "HIGH",
    expectedVerdict: "REJECT",
    branch: "demo/order-enrichment",
    changedFile: "sample-app/src/handlers/get_orders.py",
    problem:
      "주문 목록 조회 시 각 주문마다 상품 정보를 개별 조회 — 100건이면 101회 쿼리.",
    expectedKbMatch: "INC-0041",
    terminal: [
      { kind: "prompt", text: "$ ./demo.sh run h3" },
      { kind: "success", text: "✓ PR #15 생성" },
      { kind: "info", text: "→ Runtime 분석 중..." },
      {
        kind: "wait",
        label: "CodeReviewer → KB incidents + runbooks(dynamodb-best-practices)",
        durationMs: 4500,
      },
      { kind: "warn", text: "  ⚠ N+1 쿼리 패턴 감지" },
      { kind: "warn", text: "  ⚠ INC-0041 패턴 매칭 (2025-11-03)" },
      { kind: "stderr", text: "  🔴 Risk Score: 78/100 (HIGH)" },
      { kind: "stderr", text: "  판정: 🚫 REJECT" },
      ...commonFooter,
    ],
    liveCommand: { cmd: "./demo.sh", args: ["run", "h3"], expectedSeconds: 105 },
    highlightPath: [
      "github",
      "webhook",
      "analysis",
      "runtime",
      "pr_tools",
      "kb_tools",
      "kb",
      "ddb_tools",
      "slack_tools",
      "slack",
    ],
    slackPreview: {
      pr_number: 15,
      pr_title: "feat: 주문 목록에 상품 상세 정보 포함",
      pr_author: "dev-minji",
      pr_url: prUrl(15),
      change_type: "code",
      risk_score: 78,
      risk_level: "HIGH",
      verdict: "REJECT",
      summary:
        "`get_orders`가 각 주문마다 `products` 테이블을 개별 조회. 100건이면 101회.",
      issues_text:
        "• 🔴 HIGH · `get_orders.py` — N+1 쿼리 (루프 내 `get_item`)\n• 🟡 MEDIUM · 페이지네이션 파라미터 누락",
      incident_match:
        "`INC-0041` (2025-11-03) — 동일 패턴으로 API 레이턴시 P99 8.4s",
      agent_persona: "RiskJudge",
    },
  },
  // ──────────────────────────────────────────────────────────────────────
  {
    id: "h4",
    label: "H4 · Race Condition",
    title: "주문 생성 시 재고 차감 및 결제 처리",
    severity: "CRITICAL",
    expectedVerdict: "REJECT",
    branch: "demo/checkout-feature",
    changedFile: "sample-app/src/handlers/create_order.py",
    problem:
      "재고 확인(get_item)과 차감(update_item) 사이에 Race Condition. TOCTOU 취약점.",
    expectedKbMatch: "INC-0042",
    terminal: [
      { kind: "prompt", text: "$ ./demo.sh run h4" },
      { kind: "success", text: "✓ PR #16 생성" },
      { kind: "info", text: "→ Runtime 분석 중..." },
      {
        kind: "wait",
        label:
          "CodeReviewer → invoke_security_agent → KB incidents(INC-0042) → Memory 조회",
        durationMs: 5500,
      },
      { kind: "warn", text: "  ⚠ TOCTOU Race Condition 감지" },
      { kind: "warn", text: "  ⚠ INC-0042 매칭 (2026-01-15, P1, ₩12M 손실)" },
      { kind: "warn", text: "  ⚠ 같은 개발자 반복 패턴 — 가중치 +15" },
      { kind: "stderr", text: "  🔴 Risk Score: 92/100 (CRITICAL)" },
      { kind: "stderr", text: "  판정: 🚫 REJECT — 즉시 차단 권고" },
      ...commonFooter,
    ],
    liveCommand: { cmd: "./demo.sh", args: ["run", "h4"], expectedSeconds: 115 },
    highlightPath: [
      "github",
      "webhook",
      "analysis",
      "runtime",
      "pr_tools",
      "kb_tools",
      "kb",
      "ddb_tools",
      "memory",
      "slack_tools",
      "slack",
    ],
    slackPreview: {
      pr_number: 16,
      pr_title: "feat: 주문 생성 시 재고 차감 및 결제 처리",
      pr_author: "dev-ethan",
      pr_url: prUrl(16),
      change_type: "code",
      risk_score: 92,
      risk_level: "CRITICAL",
      verdict: "REJECT",
      summary:
        "`create_order.py`에서 재고 조회 후 차감까지 원자성 보장이 없음. 동시 요청 시 overselling 발생 가능.",
      issues_text:
        "• 🔴 CRITICAL · `create_order.py:17-28` — TOCTOU Race Condition\n• 🟡 MEDIUM · 보상 트랜잭션 부재 (결제 성공 + 재고 실패 시)",
      incident_match:
        "`INC-0042` (2026-01-15, P1) — 재고 -23까지 하락, 환불 23건, ₩12M 매출 손실",
      developer_pattern:
        "@dev-ethan 최근 3 PR 중 2건이 REJECT — 동시성/보안 검토 누락 패턴 반복",
      agent_persona: "RiskJudge",
    },
  },
];

export function getScenario(id: string): Scenario | undefined {
  return scenarios.find((s) => s.id === id);
}
