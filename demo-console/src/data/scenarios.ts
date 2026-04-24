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

export interface SlackIssue {
  severity: Severity;
  title: string;
  line_range?: string;
  code: string;     // snippet (fenced in the renderer)
  why: string;
  fix?: string;     // optional fix snippet
}

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
  // New-schema fields — match the real agent output
  code_block?: string;      // PR diff snippet
  issues?: SlackIssue[];    // up to ~5 findings
  incident_match?: string;  // "INC-0042 (..., P1, ₩12M 손실)"; empty if no real match
  incident_code?: string;   // past-incident code snippet paired with incident_match
  developer_pattern?: string;
  infra_impact?: string;
  agent_persona: string;
  // Legacy one-liner field — kept so older scenarios keep rendering.
  issues_text?: string;
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
      { kind: "success", text: "✓ PR #20 생성" },
      { kind: "info", text: "→ GitHub Webhook 수신, Runtime 호출 중..." },
      {
        kind: "wait",
        label: "detect_change_type → get_pr_diff → CodeReviewer → RiskJudge",
        durationMs: 3500,
      },
      { kind: "stdout", text: "  🟢 Risk Score: 20/100 (LOW)" },
      { kind: "stdout", text: "  판정: ✅ APPROVE" },
      ...commonFooter,
    ],
    liveCommand: {
      cmd: "python3",
      args: ["tools/demo_run.py", "run", "l1"],
      expectedSeconds: 95,
    },
    highlightPath: ["github", "webhook", "analysis", "runtime", "pr_tools", "slack_tools", "slack"],
    slackPreview: {
      pr_number: 20,
      pr_title: "feat: API 응답 메시지 한국어 지원",
      pr_author: "sk88ee",
      pr_url: prUrl(20),
      change_type: "code",
      risk_score: 20,
      risk_level: "LOW",
      verdict: "APPROVE",
      summary:
        "messages.py의 API 응답 메시지 7개를 영문에서 한국어로 1:1 교체한 변경입니다. 키(key) 구조는 유지되어 Breaking Change 위험은 없으나, 메시지 값을 직접 비교하는 소비자 코드 존재 여부 확인이 필요합니다. 한국어 하드코딩으로 인한 i18n 미적용이 중장기적 리스크로 남습니다.",
      code_block:
        ` MESSAGES = {
-    "order_created": "Order created successfully",
-    "order_not_found": "Order not found",
-    "order_cancelled": "Order has been cancelled",
-    "invalid_request": "Invalid request. Please check your input",
-    "order_updated": "Order updated successfully",
-    "payment_success": "Payment completed",
-    "payment_failed": "Payment failed. Please try again",
+    "order_created": "주문이 성공적으로 생성되었습니다",
+    "order_not_found": "요청하신 주문을 찾을 수 없습니다",
+    "order_cancelled": "주문이 취소되었습니다",
+    "invalid_request": "잘못된 요청입니다. 입력값을 확인해주세요",
+    "order_updated": "주문 정보가 업데이트되었습니다",
+    "payment_success": "결제가 완료되었습니다",
+    "payment_failed": "결제에 실패했습니다. 다시 시도해주세요",
 }`,
      issues: [
        {
          severity: "MEDIUM",
          title: "메시지 값 의존 소비자 영향 가능성",
          line_range: "messages.py:L1-9",
          code: `MESSAGES = {
    "order_created": "주문이 성공적으로 생성되었습니다",
    "order_not_found": "요청하신 주문을 찾을 수 없습니다",
    "order_cancelled": "주문이 취소되었습니다",
    ...
}`,
          why:
            "API 소비자(모바일 앱, 파트너 API)가 메시지 값을 문자열 동등 비교(equality check)로 사용하고 있다면, 값 변경으로 인해 클라이언트 로직 오류가 발생할 수 있습니다.",
          fix:
            "소비자 코드에서 메시지 키(key)만 사용하도록 확인하거나, API 소비자 목록(iOS, Android, 파트너 API) 대상으로 영향도 분석을 먼저 수행하세요.",
        },
        {
          severity: "MEDIUM",
          title: "i18n 미적용 — 한국어 하드코딩",
          line_range: "messages.py:L1-9",
          code: `MESSAGES = {
    "order_created": "주문이 성공적으로 생성되었습니다",
    "payment_failed": "결제에 실패했습니다. 다시 시도해주세요",
    ...
}`,
          why:
            "요청 헤더(Accept-Language)나 사용자 로케일에 무관하게 한국어가 고정 반환되어, 글로벌 확장 시 다국어 대응이 불가합니다.",
          fix:
            "gettext 또는 babel 등의 i18n 라이브러리를 도입하고, 로케일별 메시지 파일(ko.po, en.po)로 분리하는 구조를 중장기적으로 검토하세요.",
        },
        {
          severity: "LOW",
          title: "단일 언어 고정으로 인한 확장성 부족",
          line_range: "messages.py:L1-9",
          code: `MESSAGES = {
    ...
}`,
          why:
            "단일 딕셔너리 구조로는 언어별 분기가 불가능하여, 향후 다국어 지원 추가 시 전면 리팩토링이 필요합니다.",
        },
      ],
      developer_pattern:
        "sk88ee의 이전 리뷰 이력이 존재하지 않아 패턴 분석이 불가합니다. 신규 기여자로 간주하며 추가적인 멘토링이 권장됩니다.",
      agent_persona: "CodeReviewer → RiskJudge",
    },
  },
  // ──────────────────────────────────────────────────────────────────────
  {
    id: "l2",
    label: "L2 · 로깅",
    title: "구조화 로깅 적용 및 request_id 추가",
    severity: "MEDIUM",
    expectedVerdict: "APPROVE",
    branch: "demo/structured-logging",
    changedFile: "sample-app/src/handlers/*.py",
    problem: "전체 핸들러에 JSON 구조화 로그 + request_id 추가. 관측성 개선.",
    terminal: [
      { kind: "prompt", text: "$ ./demo.sh run l2" },
      { kind: "stdout", text: "Creating PR for scenario: l2" },
      { kind: "stdout", text: "  Branch: demo/structured-logging" },
      { kind: "success", text: "✓ PR #21 생성" },
      { kind: "info", text: "→ Runtime 분석 중..." },
      {
        kind: "wait",
        label: "CodeReviewer: 로깅 패턴 검토 + KB 정책 조회",
        durationMs: 3500,
      },
      { kind: "stdout", text: "  🟡 Risk Score: 25/100 (MEDIUM)" },
      { kind: "stdout", text: "  판정: ✅ APPROVE" },
      ...commonFooter,
    ],
    liveCommand: { cmd: "python3", args: ["tools/demo_run.py", "run", "l2"], expectedSeconds: 95 },
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
      pr_number: 21,
      pr_title: "refactor: 구조화 로깅 적용 및 request_id 추가",
      pr_author: "sk88ee",
      pr_url: prUrl(21),
      change_type: "code",
      risk_score: 25,
      risk_level: "MEDIUM",
      verdict: "APPROVE",
      summary:
        "plain logger 호출을 json.dumps 기반 구조화 로깅으로 교체하고 API Gateway request_id를 모든 로그 이벤트에 포함한 리팩터링입니다. 로깅 품질 개선은 긍정적이나 기존 DynamoDB scan() 전체 테이블 스캔이 그대로 유지되어 트래픽 증가 시 쓰로틀링 위험이 잠재합니다. 로깅 변경 자체의 직접 위험은 낮으나 scan() 패턴 개선을 병행 권장합니다.",
      code_block:
        ` def handler(event, context):
-    logger.info("Fetching orders")
+    request_id = event.get("requestContext", {}).get("requestId", "unknown")
+    logger.info(json.dumps({
+        "event": "fetch_orders_start",
+        "request_id": request_id,
+    }))

     try:
         response = orders_table.scan()
         orders = response["Items"]

-        logger.info(f"Found {len(orders)} orders")
+        logger.info(json.dumps({
+            "event": "fetch_orders_complete",
+            "request_id": request_id,
+            "order_count": len(orders),
+        }))

         return {
             "statusCode": 200,
             "body": json.dumps(orders, default=str),
         }
     except Exception as e:
-        logger.error(f"Error fetching orders: {str(e)}")
+        logger.error(json.dumps({
+            "event": "fetch_orders_error",
+            "request_id": request_id,
+            "error": str(e),
+        }))`,
      issues: [
        {
          severity: "MEDIUM",
          title: "DynamoDB scan() 전체 테이블 스캔 유지",
          line_range: "get_orders.py:L17",
          code: `response = orders_table.scan()
orders = response["Items"]`,
          why:
            "scan()은 테이블 전체를 읽어 RCU를 대량 소비하며, 데이터 증가 시 쓰로틀링·응답 지연·연쇄 장애를 유발합니다. 1MB 초과 결과는 페이지네이션 없이 잘려 데이터 누락이 발생할 수 있습니다.",
          fix: `response = orders_table.scan(Limit=50)
orders = response.get("Items", [])
last_key = response.get("LastEvaluatedKey")
# 장기적으로 Query + GSI 전환 권장`,
        },
        {
          severity: "LOW",
          title: "str(e) 예외 전체 문자열 로그 노출",
          line_range: "get_orders.py:L35-L39",
          code: `logger.error(json.dumps({
    "event": "fetch_orders_error",
    "request_id": request_id,
    "error": str(e),
}))`,
          why:
            "str(e)는 DynamoDB 테이블명, 내부 엔드포인트 등 구현 세부 정보를 포함할 수 있어 CloudWatch 로그를 통한 내부 정보 노출 리스크가 있습니다.",
          fix: `logger.error(json.dumps({
    "event": "fetch_orders_error",
    "request_id": request_id,
    "error": type(e).__name__,
}))`,
        },
      ],
      developer_pattern:
        "sk88ee의 이전 리뷰 이력이 없어 반복 패턴 분석 불가합니다. 프로파일 미등록 상태로 첫 기여이거나 신규 등록이 필요합니다.",
      agent_persona: "CodeReviewer → RiskJudge",
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
      { kind: "success", text: "✓ PR #22 생성" },
      { kind: "info", text: "→ Runtime 분석 중..." },
      {
        kind: "wait",
        label: "CodeReviewer → invoke_security_agent → KB incidents 조회",
        durationMs: 5000,
      },
      { kind: "warn", text: "  ⚠ 하드코딩된 API 키 패턴 감지" },
      { kind: "warn", text: "  ⚠ INC-0045 (시크릿 유출, 2025-12-08) 매칭" },
      { kind: "stderr", text: "  🔴 Risk Score: 92/100 (CRITICAL)" },
      { kind: "stderr", text: "  판정: 🚫 REJECT — CI/CD 파이프라인 차단" },
      ...commonFooter,
    ],
    liveCommand: { cmd: "python3", args: ["tools/demo_run.py", "run", "h1"], expectedSeconds: 110 },
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
      pr_number: 22,
      pr_title: "feat: 외부 결제 서비스 연동",
      pr_author: "sk88ee",
      pr_url: prUrl(22),
      change_type: "code",
      risk_score: 92,
      risk_level: "CRITICAL",
      verdict: "REJECT",
      summary:
        "신규 결제 처리 파일에 프로덕션 라이브 API 키(sk_live_*)와 Webhook Secret이 하드코딩되어 Git 히스토리에 영구 노출되었습니다. 동시에 카드 토큰이 DEBUG/ERROR 로그에 평문 기록되어 PCI DSS를 위반합니다. 과거 동일 패턴의 P1 장애(INC-0045, ₩5M 손실)가 존재하며, 즉각적인 시크릿 폐기 및 로테이션이 필요합니다.",
      code_block:
        `+# 외부 결제 서비스 연동
+PAYMENT_API_URL = "https://api.payments.example.com/v1"
+PAYMENT_API_KEY = "sk_live_a1b2c3d4e5f6g7h8i9j0"  # TODO: 나중에 환경변수로 바꾸기
+PAYMENT_WEBHOOK_SECRET = "whsec_prod_x9y8z7w6v5u4t3"
+
+def process_payment(user_id, amount, card_token):
+    logger.info(f"Processing payment for user {user_id}")
+    logger.debug(f"Payment details: user={user_id}, amount={amount}, card={card_token}")
+
+    response = requests.post(
+        f"{PAYMENT_API_URL}/charges",
+        headers={"Authorization": f"Bearer {PAYMENT_API_KEY}"},
+        json={
+            "amount": int(amount * 100),
+            "currency": "krw",
+            "card_token": card_token,
+        }
+    )  # timeout 없음
+
+    logger.debug(f"Payment response: {response.json()}")
+
+    if response.status_code != 200:
+        logger.error(f"Payment failed for user {user_id}, card: {card_token}, error: {response.text}")
+        raise Exception(f"결제 실패: {response.text}")
+
+    return response.json()`,
      issues: [
        {
          severity: "CRITICAL",
          title: "프로덕션 라이브 API 키 하드코딩",
          line_range: "process_payment.py:L9-10",
          code: `PAYMENT_API_KEY = "sk_live_a1b2c3d4e5f6g7h8i9j0"  # TODO: 나중에 환경변수로 바꾸기
PAYMENT_WEBHOOK_SECRET = "whsec_prod_x9y8z7w6v5u4t3"`,
          why:
            "sk_live_* 프리픽스는 프로덕션 라이브 키이며 Git 히스토리에 영구 기록됩니다. 악의적 행위자가 즉시 API를 무단 호출할 수 있습니다.",
          fix: `import boto3, json

def _get_secret(secret_name: str) -> str:
    client = boto3.client("secretsmanager")
    return json.loads(client.get_secret_value(SecretId=secret_name)["SecretString"])["value"]

PAYMENT_API_KEY = _get_secret("payment/api-key")
PAYMENT_WEBHOOK_SECRET = _get_secret("payment/webhook-secret")`,
        },
        {
          severity: "CRITICAL",
          title: "카드 토큰 로그 평문 노출 (PCI DSS 위반)",
          line_range: "process_payment.py:L21,L39",
          code: `logger.debug(f"Payment details: user={user_id}, amount={amount}, card={card_token}")
logger.error(f"Payment failed for user {user_id}, card: {card_token}, error: {response.text}")`,
          why:
            "card_token이 DEBUG와 ERROR 레벨 모두에서 CloudWatch Logs에 평문 저장됩니다. PCI DSS Requirement 3.4 위반으로 규제 패널티 대상입니다.",
          fix: `logger.info(f"Processing payment for user {user_id}, amount={amount}")
# card_token 은 절대 로그에 포함하지 않음
logger.error(f"Payment failed for user {user_id}, status={response.status_code}")`,
        },
        {
          severity: "HIGH",
          title: "외부 API 호출 timeout 미설정",
          line_range: "process_payment.py:L23-33",
          code: `response = requests.post(
    f"{PAYMENT_API_URL}/charges",
    headers={"Authorization": f"Bearer {PAYMENT_API_KEY}"},
    json={...}
    # timeout 파라미터 없음
)`,
          why:
            "결제 API 지연 시 Lambda/서버 스레드가 무한 대기하여 연쇄 장애를 유발합니다.",
          fix: `response = requests.post(
    f"{PAYMENT_API_URL}/charges",
    headers={"Authorization": f"Bearer {PAYMENT_API_KEY}"},
    json={...},
    timeout=(3.05, 10)
)`,
        },
        {
          severity: "HIGH",
          title: "네트워크 예외 미처리 — 결제 상태 불명확",
          line_range: "process_payment.py:L35-41",
          code: `if response.status_code != 200:
    raise Exception(f"결제 실패: {response.text}")
return response.json()`,
          why:
            "ConnectionError, Timeout, JSONDecodeError 등 네트워크 레벨 예외가 처리되지 않아 결제 성공/실패 상태가 불명확해집니다.",
          fix: `try:
    response = requests.post(..., timeout=(3.05, 10))
    response.raise_for_status()
    return response.json()
except requests.exceptions.Timeout:
    logger.error(f"Payment API timeout for user {user_id}")
    raise
except requests.exceptions.RequestException as e:
    logger.error(f"Payment API error: {type(e).__name__}")
    raise`,
        },
        {
          severity: "MEDIUM",
          title: "멱등성 없음 — 중복 결제 위험",
          line_range: "process_payment.py:L23-33",
          code: `response = requests.post(
    f"{PAYMENT_API_URL}/charges",
    headers={"Authorization": f"Bearer {PAYMENT_API_KEY}"},
    json={...}
)`,
          why:
            "재시도 시 동일 결제 요청이 중복 처리될 수 있습니다. Idempotency-Key 헤더가 없습니다.",
          fix: `import uuid
headers = {
    "Authorization": f"Bearer {PAYMENT_API_KEY}",
    "Idempotency-Key": str(uuid.uuid4())
}`,
        },
      ],
      incident_match:
        "INC-0045 (2026-02-08, P1, ₩5,000,000 손실) — sk_live_* 하드코딩 + card_token 로그 노출, 동일 파일(process_payment.py), 완전히 동일한 취약점 패턴",
      incident_code: `PAYMENT_API_KEY = "sk_live_a1b2c3d4e5f6"  # TODO: 나중에 환경변수로 바꾸기
logger.debug(f"Payment details: card={card_token}")`,
      developer_pattern:
        "sk88ee는 이 레포에서 첫 번째 PR 제출로 리뷰 이력이 없습니다. INC-0045와 완전히 동일한 시크릿 하드코딩 + TODO 주석 패턴을 재현하여 Risk Score에 +15 가중치가 적용되었습니다.",
      agent_persona: "CodeReviewer → invoke_security_agent → RiskJudge",
    },
  },
  // ──────────────────────────────────────────────────────────────────────
  {
    id: "h2",
    label: "H2 · Breaking API",
    title: "API 응답 필드명 컨벤션 통일",
    severity: "CRITICAL",
    expectedVerdict: "REJECT",
    branch: "demo/api-cleanup",
    changedFile: "sample-app/src/handlers/get_orders.py",
    problem:
      "응답 필드명을 snake_case로 바꾸면서 기존 클라이언트 호환성을 깨뜨림.",
    expectedKbMatch: "INC-0038",
    terminal: [
      { kind: "prompt", text: "$ ./demo.sh run h2" },
      { kind: "success", text: "✓ PR #23 생성" },
      { kind: "info", text: "→ Runtime 분석 중..." },
      {
        kind: "wait",
        label: "CodeReviewer → KB runbooks(api-change-policy) 조회",
        durationMs: 4500,
      },
      { kind: "warn", text: "  ⚠ Breaking API Change — 필드명 변경" },
      { kind: "warn", text: "  ⚠ INC-0038 패턴 매칭 (2025-10-22)" },
      { kind: "stderr", text: "  🔴 Risk Score: 85/100 (CRITICAL)" },
      { kind: "stderr", text: "  판정: 🚫 REJECT — CI/CD 파이프라인 차단" },
      ...commonFooter,
    ],
    liveCommand: { cmd: "python3", args: ["tools/demo_run.py", "run", "h2"], expectedSeconds: 105 },
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
      pr_number: 23,
      pr_title: "refactor: API 응답 필드명 컨벤션 통일",
      pr_author: "sk88ee",
      pr_url: prUrl(23),
      change_type: "code",
      risk_score: 85,
      risk_level: "CRITICAL",
      verdict: "REJECT",
      summary:
        "get_order.py에서 orderId·order_status·totalPrice·orderItems 4개 필드명을 API 버저닝 없이 일괄 변경하고 userId 필드를 삭제한 PR입니다. 과거 동일 파일·동일 패턴으로 INC-0038(P2, ₩3.5M 손실) 장애가 발생한 바 있으며, PR#17에서도 동일 패턴이 CRITICAL REJECT된 반복 시도입니다. Breaking Change 정책 위반으로 즉시 REJECT합니다.",
      code_block:
        `@@ -25,16 +25,17 @@ def handler(event, context):
                 "body": json.dumps({"error": MESSAGES["order_not_found"]}),
             }

+        # Refactored: snake_case 통일, 불필요 필드 제거
         return {
             "statusCode": 200,
             "headers": {"Content-Type": "application/json"},
             "body": json.dumps({
-                "orderId": order["orderId"],
-                "order_status": order["status"],
-                "totalPrice": order["totalPrice"],
+                "id": order["orderId"],
+                "status": order["status"],
+                "total_price": order["totalPrice"],
                 "created_at": order["createdAt"],
-                "orderItems": order.get("items", []),
-                "userId": order["userId"],
+                "items": order.get("items", []),
+                # userId 제거 — 프론트에서 사용하지 않음
             }, default=str),
         }`,
      issues: [
        {
          severity: "CRITICAL",
          title: "Breaking API Change — 4개 필드명 동시 변경",
          line_range: "get_order.py:L28-38",
          code: `-                "orderId": order["orderId"],
-                "order_status": order["status"],
-                "totalPrice": order["totalPrice"],
-                "orderItems": order.get("items", []),
+                "id": order["orderId"],
+                "status": order["status"],
+                "total_price": order["totalPrice"],
+                "items": order.get("items", []),`,
          why:
            "API 버저닝 없이 4개 필드명을 일괄 변경하면 기존 소비자(모바일 앱, 파트너 API)의 JSON 파싱이 즉시 실패합니다. INC-0038에서 동일 패턴으로 45분 장애·₩3.5M 손실이 발생한 전례가 있습니다.",
          fix: `# 기존 필드 유지 + 신규 필드 병행 추가 (하위 호환성)
"orderId": order["orderId"],        # 기존 유지
"id": order["orderId"],             # 신규 추가 (Deprecated 예정)
"order_status": order["status"],    # 기존 유지
"status": order["status"],          # 신규 추가
"totalPrice": order["totalPrice"],  # 기존 유지
"total_price": order["totalPrice"], # 신규 추가`,
        },
        {
          severity: "HIGH",
          title: "userId 필드 삭제 — 소비자 영향 미확인",
          line_range: "get_order.py:L38",
          code: `-                "userId": order["userId"],
+                # userId 제거 — 프론트에서 사용하지 않음`,
          why:
            "프론트엔드 외 모바일 앱·파트너 API·백엔드 서비스의 userId 사용 여부가 확인되지 않았습니다. userId는 인가 로직에도 활용될 수 있어 삭제 시 보안 및 접근 제어에 영향을 줄 수 있습니다.",
          fix: `# userId는 삭제하지 않고 Deprecated 표시 후 2스프린트 유예
"userId": order["userId"],  # DEPRECATED: v2에서 제거 예정, 2026-QX 이후`,
        },
      ],
      incident_match:
        "INC-0038 (2025-11-22, P2, ₩3,500,000 손실) — get_order.py 동일 파일에서 orderId→id, totalPrice→total_price, orderItems→items 동일 필드명 변경으로 모바일 앱 크래시(크래시율 0.1%→34%, 45분 장애)",
      incident_code: `# INC-0038 재현 패턴 (출처: incidents/INC-0038-breaking-api.md)
# 필드명 변경 — 외부 소비자(모바일 앱) 영향 미고려
return {
  "id": order['orderId'],            # 기존: orderId
  "status": order['status'],         # 기존: order_status
  "total_price": order['totalPrice'],# 기존: totalPrice
}`,
      developer_pattern:
        "sk88ee는 DDB 프로필 미등록 신규 기여자이나, 세션 이력상 PR#17에서 동일한 get_order.py 필드명 변경+userId 삭제가 이미 CRITICAL REJECT된 바 있습니다. 동일 패턴을 반복 시도하는 경향이 확인되어 Risk Score에 +10 가중치가 적용되었습니다.",
      agent_persona: "CodeReviewer → RiskJudge",
    },
  },
  // ──────────────────────────────────────────────────────────────────────
  {
    id: "h3",
    label: "H3 · N+1 쿼리",
    title: "주문 목록에 상품 상세 정보 포함",
    severity: "CRITICAL",
    expectedVerdict: "REJECT",
    branch: "demo/order-enrichment",
    changedFile: "sample-app/src/handlers/get_orders.py",
    problem:
      "주문 목록 조회 시 각 주문마다 상품 정보를 개별 조회 — 100건이면 101회 쿼리.",
    expectedKbMatch: "INC-0041",
    terminal: [
      { kind: "prompt", text: "$ ./demo.sh run h3" },
      { kind: "success", text: "✓ PR #24 생성" },
      { kind: "info", text: "→ Runtime 분석 중..." },
      {
        kind: "wait",
        label: "CodeReviewer → KB incidents + runbooks(dynamodb-best-practices)",
        durationMs: 4500,
      },
      { kind: "warn", text: "  ⚠ N+1 쿼리 패턴 감지" },
      { kind: "warn", text: "  ⚠ INC-0041 패턴 매칭 (2025-11-03)" },
      { kind: "stderr", text: "  🔴 Risk Score: 85/100 (CRITICAL)" },
      { kind: "stderr", text: "  판정: 🚫 REJECT — CI/CD 파이프라인 차단" },
      ...commonFooter,
    ],
    liveCommand: { cmd: "python3", args: ["tools/demo_run.py", "run", "h3"], expectedSeconds: 105 },
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
      pr_number: 24,
      pr_title: "feat: 주문 목록에 상품 상세 정보 포함",
      pr_author: "sk88ee",
      pr_url: prUrl(24),
      change_type: "code",
      risk_score: 85,
      risk_level: "CRITICAL",
      verdict: "REJECT",
      summary:
        "신규 list_orders.py 핸들러에서 DynamoDB 전체 테이블 scan()과 루프 내 N+1 get_item() 개별 호출이 동시에 도입되었습니다. 이는 INC-0041(2025-12-20, P1, 매출 손실 ₩8,200만)과 완전히 동일한 코드 패턴으로, 프로덕션 배포 시 DynamoDB 쓰로틀링 및 연쇄 장애가 재현될 위험이 매우 높습니다.",
      code_block:
        `+def handler(event, context):
+    logger.info("Fetching orders with product details")
+
+    # 전체 주문 조회 (페이지네이션 없음)
+    orders = orders_table.scan()["Items"]
+
+    # 주문마다 상품 상세 정보를 개별 조회
+    enriched_orders = []
+    for order in orders:
+        product = products_table.get_item(
+            Key={"productId": order["productId"]}
+        )["Item"]
+
+        enriched_orders.append({
+            "orderId": order["orderId"],
+            "status": order["status"],
+            "quantity": order["quantity"],
+            "product": {
+                "name": product["name"],
+                "description": product["description"],
+                "price": product["price"],
+                "imageUrl": product["imageUrl"],
+                "specifications": product.get("specifications", {}),
+                "reviews": product.get("reviews", []),
+            }
+        })
+
+    return {
+        "statusCode": 200,
+        "headers": {"Content-Type": "application/json"},
+        "body": json.dumps(enriched_orders, default=str),
+    }`,
      issues: [
        {
          severity: "CRITICAL",
          title: "N+1 쿼리 — 루프 내 get_item() 개별 호출",
          line_range: "L22-26",
          code: `for order in orders:
    product = products_table.get_item(
        Key={"productId": order["productId"]}
    )["Item"]`,
          why:
            "주문 건수 N개마다 DynamoDB get_item을 1회씩 호출해 프로덕션 50,000건 시 50,001회 호출 발생. INC-0041과 동일한 패턴으로 DynamoDB 쓰로틀링 및 주문·결제 API 연쇄 장애를 유발합니다.",
          fix: `product_ids = list({o["productId"] for o in orders})
chunks = [product_ids[i:i+100] for i in range(0, len(product_ids), 100)]
products = {}
for chunk in chunks:
    resp = dynamodb.batch_get_item(
        RequestItems={os.environ["PRODUCTS_TABLE"]: {"Keys": [{"productId": pid} for pid in chunk]}}
    )
    for item in resp["Responses"][os.environ["PRODUCTS_TABLE"]]:
        products[item["productId"]] = item`,
        },
        {
          severity: "CRITICAL",
          title: "DynamoDB 전체 테이블 scan() — 페이지네이션 없음",
          line_range: "L17",
          code: `orders = orders_table.scan()["Items"]  # 전체 스캔, 페이지네이션 없음`,
          why:
            "scan()은 테이블 전체를 읽어 RCU를 대량 소비하며, 응답 크기가 API Gateway 10MB 한도 초과 시 502 Bad Gateway가 발생합니다. 사내 DynamoDB 가이드라인에서 프로덕션 API의 scan() 사용을 명시적으로 금지하고 있습니다.",
          fix: `def scan_with_pagination(table, limit=50, last_key=None):
    kwargs = {"Limit": limit}
    if last_key:
        kwargs["ExclusiveStartKey"] = last_key
    resp = table.scan(**kwargs)
    return resp.get("Items", []), resp.get("LastEvaluatedKey")`,
        },
        {
          severity: "HIGH",
          title: "KeyError 미처리 — Item/필드 직접 접근",
          line_range: "L23-37",
          code: `product = products_table.get_item(
    Key={"productId": order["productId"]}
)["Item"]   # Item 없으면 KeyError
"name": product["name"],
"price": product["price"],`,
          why:
            "상품이 삭제됐거나 데이터 정합성 이슈가 있으면 'Item' 키 또는 필드가 없어 KeyError가 발생하고 전체 주문 목록 API가 500 에러를 반환합니다.",
          fix: `product = products_table.get_item(
    Key={"productId": order.get("productId")}
).get("Item")
if not product:
    continue
"name": product.get("name", ""),
"price": product.get("price", 0),`,
        },
        {
          severity: "MEDIUM",
          title: "대용량 페이로드 — reviews/specifications 전체 반환",
          line_range: "L36-37",
          code: `"specifications": product.get("specifications", {}),
"reviews": product.get("reviews", []),`,
          why:
            "목록 API에서 리뷰 전체와 상세 스펙을 반환하면 응답 페이로드가 비대해져 Lambda 실행 시간 초과 및 API Gateway 10MB 제한에 걸릴 수 있습니다.",
        },
      ],
      incident_match:
        "INC-0041 (2025-12-20, P1, 매출 손실 ₩8,200,000 + 추가 과금 ₩2,100,000) — 동일 파일(list_orders.py), 동일 패턴(scan + N+1 get_item)",
      incident_code: `orders = orders_table.scan()['Items']  # 전체 스캔, 페이지네이션 없음
for order in orders:
    product = products_table.get_item(  # N+1 쿼리
        Key={'productId': order['productId']}
    )['Item']`,
      developer_pattern:
        "sk88ee의 과거 리뷰 이력이 존재하지 않아 신규 기여자로 판단됩니다. DynamoDB scan 금지, 페이지네이션 필수, BatchGetItem 사용 등 사내 DynamoDB 가이드라인 온보딩이 필요합니다.",
      agent_persona: "CodeReviewer → RiskJudge",
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
      { kind: "success", text: "✓ PR #25 생성" },
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
      { kind: "stderr", text: "  🔴 Risk Score: 95/100 (CRITICAL)" },
      { kind: "stderr", text: "  판정: 🚫 REJECT — 즉시 차단 권고" },
      ...commonFooter,
    ],
    liveCommand: { cmd: "python3", args: ["tools/demo_run.py", "run", "h4"], expectedSeconds: 115 },
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
      pr_number: 25,
      pr_title: "feat: 주문 생성 시 재고 차감 및 결제 처리",
      pr_author: "sk88ee",
      pr_url: prUrl(25),
      change_type: "code",
      risk_score: 95,
      risk_level: "CRITICAL",
      verdict: "REJECT",
      summary:
        "이 PR은 DynamoDB 재고 차감 시 ConditionExpression을 제거하여 TOCTOU Race Condition을 유발하는 코드로 회귀하였습니다. 2026-01-15 P1 장애(INC-0042, ₩12M 손실)와 완전히 동일한 패턴이며, 입력값 검증 제거 및 결제-재고 비원자적 처리까지 복합적인 위험이 존재합니다. 즉시 수정 없이 머지할 수 없습니다.",
      code_block:
        `-    try:
-        body = json.loads(event["body"])
-        product_id = body["product_id"]
-        quantity = body["quantity"]
-        user_id = body["user_id"]
-    except (json.JSONDecodeError, KeyError) as e:
-        return {"statusCode": 400, "body": json.dumps({"error": "Invalid request body"})}
+    body = json.loads(event["body"])
+    product_id = body["product_id"]
+    quantity = body["quantity"]
+    user_id = body["user_id"]

+    # Step 1: 재고 확인
+    inventory = inventory_table.get_item(Key={"productId": product_id})["Item"]
+    available = inventory["stockCount"]

-    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
-        return {"statusCode": 400, "body": json.dumps({"error": "Insufficient stock"})}
+    if available < quantity:
+        return {"statusCode": 400, "body": "재고가 부족합니다"}

+    # Step 2: 재고 차감 (ConditionExpression 없음!)
+    inventory_table.update_item(
+        Key={"productId": product_id},
+        UpdateExpression="SET stockCount = stockCount - :qty",
+        ExpressionAttributeValues={":qty": quantity},
+    )
+    orders_table.put_item(Item={"orderId": order_id, ...})
+    payment_result = process_payment(user_id, inventory["price"] * quantity)

+def process_payment(user_id, amount):
+    # TODO: 외부 결제 API 연동
+    return {"status": "success"}`,
      issues: [
        {
          severity: "CRITICAL",
          title: "TOCTOU Race Condition — 재고 overselling",
          line_range: "create_order.py:L30-38",
          code: `inventory = inventory_table.get_item(Key={"productId": product_id})["Item"]
available = inventory["stockCount"]
if available < quantity:
    return {"statusCode": 400, "body": "재고가 부족합니다"}
inventory_table.update_item(
    Key={"productId": product_id},
    UpdateExpression="SET stockCount = stockCount - :qty",
    ExpressionAttributeValues={":qty": quantity},
)`,
          why:
            "get_item 읽기와 update_item 쓰기 사이에 동시 요청이 끼어들어 동일 재고를 중복 차감, 재고가 음수(overselling)가 됩니다. INC-0042의 근본 원인과 완전히 동일한 패턴입니다.",
          fix: `try:
    inventory_table.update_item(
        Key={"productId": product_id},
        UpdateExpression="SET stockCount = stockCount - :qty",
        ConditionExpression="stockCount >= :qty",
        ExpressionAttributeValues={":qty": quantity},
    )
except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
    return {"statusCode": 400, "body": json.dumps({"error": "Insufficient stock"})}`,
        },
        {
          severity: "HIGH",
          title: "입력값 파싱 try/except 전면 제거",
          line_range: "create_order.py:L18-21",
          code: `body = json.loads(event["body"])
product_id = body["product_id"]
quantity = body["quantity"]
user_id = body["user_id"]`,
          why:
            "잘못된 JSON 또는 필수 필드 누락 시 Lambda가 unhandled exception으로 500을 반환하고 스택 트레이스가 외부에 노출됩니다.",
          fix: `try:
    body = json.loads(event["body"])
    product_id = body["product_id"]
    quantity = body["quantity"]
    user_id = body["user_id"]
except (json.JSONDecodeError, KeyError) as e:
    return {"statusCode": 400, "body": json.dumps({"error": "Invalid request body"})}`,
        },
        {
          severity: "HIGH",
          title: "결제-재고 비원자적 처리 (롤백 없음)",
          line_range: "create_order.py:L44-46",
          code: `orders_table.put_item(Item={...})
payment_result = process_payment(user_id, inventory["price"] * quantity)
return {"statusCode": 201, "body": json.dumps({"orderId": order_id})}`,
          why:
            "재고 차감 및 주문 생성 이후 결제가 실패해도 이미 확정된 재고 차감과 주문이 롤백되지 않아 재고 손실 및 유령 주문이 발생합니다.",
        },
        {
          severity: "MEDIUM",
          title: "process_payment() 미구현 stub (항상 success 반환)",
          line_range: "create_order.py:L50-53",
          code: `def process_payment(user_id, amount):
    logger.info(f"Processing payment: user={user_id}, amount={amount}")
    # TODO: 외부 결제 API 연동
    return {"status": "success"}`,
          why:
            "실제 결제 처리 없이 항상 성공을 반환하는 stub 함수로, 프로덕션 배포 시 무결제 주문 확정이 발생합니다.",
        },
      ],
      incident_match:
        "INC-0042 (2026-01-15, P1, ₩12,000,000 손실) — 동일 파일, 동일 TOCTOU 패턴 재발",
      incident_code: `# Step 1: 재고 확인 (읽기)
inventory = inventory_table.get_item(Key={'productId': product_id})['Item']
available = inventory['stockCount']
if available < quantity:
    return error
# Step 2: 재고 차감 (쓰기) — 이 사이에 다른 요청이 끼어들 수 있음
inventory_table.update_item(
    UpdateExpression='SET stockCount = stockCount - :qty',
    ExpressionAttributeValues={':qty': quantity}
)`,
      developer_pattern:
        "sk88ee는 신규 기여자로 과거 리뷰 이력이 없습니다. DynamoDB 낙관적 잠금(ConditionExpression) 및 동시성 제어 패턴에 대한 교육이 필요합니다.",
      agent_persona: "CodeReviewer → invoke_security_agent → RiskJudge",
    },
  },
  // ──────────────────────────────────────────────────────────────────────
  {
    id: "i1",
    label: "I1 · 태그 + 로그 보존",
    title: "거버넌스 태그 + CloudWatch 로그 보존 90일",
    severity: "MEDIUM",
    expectedVerdict: "APPROVE",
    branch: "demo/infra-tagging",
    changedFile: "sample-app/template.yaml",
    problem:
      "모든 리소스에 Environment/Owner/CostCenter/Project 태그 추가 + Lambda 별 LogGroup을 명시해 RetentionInDays=90 적용. 런타임 동작·비용·권한 변화 없음, 거버넌스만 개선.",
    terminal: [
      { kind: "prompt", text: "$ python3 tools/demo_run.py run i1" },
      { kind: "stdout", text: "Creating PR for scenario: i1" },
      { kind: "stdout", text: "  Branch: demo/infra-tagging" },
      { kind: "success", text: "✓ PR #26 생성" },
      { kind: "info", text: "→ Runtime 분석 중..." },
      {
        kind: "wait",
        label:
          "detect_change_type=iac → InfraReviewer → KB runbooks(tagging-policy)",
        durationMs: 4000,
      },
      { kind: "stdout", text: "  🟡 Risk Score: 35/100 (MEDIUM)" },
      { kind: "stdout", text: "  판정: ✅ APPROVE" },
      ...commonFooter,
    ],
    liveCommand: {
      cmd: "python3",
      args: ["tools/demo_run.py", "run", "i1"],
      expectedSeconds: 95,
    },
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
      pr_number: 26,
      pr_title: "chore(infra): 거버넌스 태그 + 로그 보존 90일",
      pr_author: "sk88ee",
      pr_url: prUrl(26),
      change_type: "iac",
      risk_score: 35,
      risk_level: "MEDIUM",
      verdict: "APPROVE",
      summary:
        "sample-app/template.yaml에 거버넌스 태그 4종과 Lambda LogGroup 4개를 추가하는 순수 인프라 변경입니다. IAM 변경이 없어 보안 위험은 낮으나, 기존에 자동 생성된 LogGroup과 이름 충돌 시 배포 실패 가능성이 있으므로 배포 전 확인이 필요합니다. DeletionPolicy 미설정 및 환경값 하드코딩은 운영 안정성 관점에서 개선이 권장됩니다.",
      code_block:
        `@@ -48,21 +48,21 @@ Resources:
+  GetOrdersFunctionLogGroup:
+    Type: AWS::Logs::LogGroup
+    Properties:
+      LogGroupName: !Sub /aws/lambda/\${GetOrdersFunction}
+      RetentionInDays: 90
+      Tags:
+        - Key: Environment
+          Value: prod
+        - Key: Owner
+          Value: orders-platform
+        - Key: CostCenter
+          Value: CC-1042
+        - Key: Project
+          Value: aiops-changemgmt
+
+  CreateOrderFunctionLogGroup:
+    Type: AWS::Logs::LogGroup
+    Properties:
+      LogGroupName: !Sub /aws/lambda/\${CreateOrderFunction}
+      RetentionInDays: 90
+      Tags:
+        - Key: Environment
+          Value: prod
   OrdersTable:
     Type: AWS::DynamoDB::Table
     Properties:
       BillingMode: PAY_PER_REQUEST
+      Tags:
+        - Key: Environment
+          Value: prod
+        - Key: CostCenter
+          Value: CC-1042`,
      infra_impact:
        "Lambda 4개 함수에 CloudWatch LogGroup 명시적 관리 추가(RetentionInDays: 90). 기존 자동생성 LogGroup과 이름 충돌 시 배포 실패 가능. DynamoDB 3개 테이블 및 API Gateway에 태그 추가(데이터 영향 없음). IAM 변경 없음.",
      issues: [
        {
          severity: "MEDIUM",
          title: "기존 LogGroup 충돌 — AlreadyExistsException",
          line_range: "GetOrdersFunctionLogGroup:L51",
          code: `GetOrdersFunctionLogGroup:
  Type: AWS::Logs::LogGroup
  Properties:
    LogGroupName: !Sub /aws/lambda/\${GetOrdersFunction}
    RetentionInDays: 90`,
          why:
            "Lambda가 이미 실행된 적 있으면 동일 이름의 LogGroup이 CloudWatch에 자동 생성되어 있으며, CFN이 같은 이름으로 리소스를 생성하려 하면 AlreadyExistsException으로 스택 배포가 실패합니다.",
          fix: `GetOrdersFunctionLogGroup:
  Type: AWS::Logs::LogGroup
  DeletionPolicy: Retain
  Properties:
    LogGroupName: !Sub /aws/lambda/\${GetOrdersFunction}
    RetentionInDays: 90
# 배포 전: aws logs describe-log-groups --log-group-name-prefix /aws/lambda/ 로 확인 필수`,
        },
        {
          severity: "MEDIUM",
          title: "LogGroup DeletionPolicy 미설정 — 로그 소실 위험",
          line_range: "GetOrdersFunctionLogGroup ~ GetProductsFunctionLogGroup",
          code: `GetOrdersFunctionLogGroup:
  Type: AWS::Logs::LogGroup
  Properties:
    LogGroupName: !Sub /aws/lambda/\${GetOrdersFunction}
    RetentionInDays: 90
    # DeletionPolicy 없음`,
          why:
            "DeletionPolicy가 없으면 CFN 스택 삭제 시 LogGroup과 90일치 로그가 함께 삭제되어 감사 추적 및 사후 장애 분석이 불가능해집니다.",
          fix: `GetOrdersFunctionLogGroup:
  Type: AWS::Logs::LogGroup
  DeletionPolicy: Retain
  Properties:
    LogGroupName: !Sub /aws/lambda/\${GetOrdersFunction}
    RetentionInDays: 90`,
        },
        {
          severity: "MEDIUM",
          title: "Environment 태그 하드코딩 (prod)",
          line_range: "Globals.Tags + 전체 Resources",
          code: `Globals:
  Function:
    Tags:
      Environment: prod
      Owner: orders-platform
      CostCenter: CC-1042
      Project: aiops-changemgmt`,
          why:
            "환경값이 prod로 하드코딩되어 있어 동일 템플릿을 dev/staging에 배포 시 모든 리소스가 prod로 태깅되어 비용 배분 및 환경 추적이 오염됩니다.",
          fix: `Parameters:
  Environment:
    Type: String
    Default: prod
    AllowedValues: [dev, staging, prod]
# Tags에서:
      Environment: !Ref Environment`,
        },
        {
          severity: "LOW",
          title: "로그 보존 90일 — 정책 권장(30일) 초과",
          line_range: "RetentionInDays: 90 (4개 LogGroup)",
          code: `RetentionInDays: 90`,
          why:
            "내부 IaC 검토 정책은 불필요한 CloudWatch 로그 과다 보존을 금지하고 30일을 권장합니다. 90일 설정은 월별 로그 스토리지 비용 증가를 초래합니다.",
          fix: `RetentionInDays: 30  # 컴플라이언스 요건 없으면 30일 권장`,
        },
      ],
      developer_pattern:
        "sk88ee는 이 레포에서 첫 IaC 기여자로 과거 리뷰 이력이 없습니다. DeletionPolicy, CFN 파라미터화 등 IaC 모범 사례에 대한 추가 가이드 제공을 권장합니다.",
      agent_persona: "InfraReviewer → RiskJudge",
    },
  },
  // ──────────────────────────────────────────────────────────────────────
  {
    id: "i2",
    label: "I2 · SG Egress 제한",
    title: "Lambda 보안그룹 egress를 내부 CIDR로 제한",
    severity: "CRITICAL",
    expectedVerdict: "REJECT",
    branch: "demo/sg-egress-tightening",
    changedFile: "sample-app/template.yaml",
    problem:
      "Lambda를 VPC에 배치하고 LambdaSecurityGroup egress를 10.0.0.0/8로 제한. VPC Endpoint 미구성 상태로 머지 시 Secrets Manager / DynamoDB / STS 등 AWS 컨트롤 플레인 호출이 모두 실패 — 주문 API 전면 장애.",
    expectedKbMatch: "INC-0040",
    terminal: [
      { kind: "prompt", text: "$ python3 tools/demo_run.py run i2" },
      { kind: "success", text: "✓ PR #28 생성" },
      { kind: "info", text: "→ Runtime 분석 중..." },
      {
        kind: "wait",
        label:
          "InfraReviewer → invoke_security_agent → KB runbooks(vpc-egress-policy)",
        durationMs: 5500,
      },
      { kind: "warn", text: "  ⚠ Lambda VPC 배치 + egress 10.0.0.0/8 제한" },
      { kind: "warn", text: "  ⚠ VPC Endpoint 미구성 — DynamoDB/STS 접근 차단" },
      { kind: "warn", text: "  ⚠ Globals.VpcConfig 일괄 적용 — 4개 Lambda 동시 영향" },
      { kind: "stderr", text: "  🔴 Risk Score: 87/100 (CRITICAL)" },
      { kind: "stderr", text: "  판정: 🚫 REJECT — 즉시 차단 권고" },
      ...commonFooter,
    ],
    liveCommand: {
      cmd: "python3",
      args: ["tools/demo_run.py", "run", "i2"],
      expectedSeconds: 110,
    },
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
      pr_number: 28,
      pr_title: "feat(infra): Lambda 보안그룹 egress를 내부 CIDR로 제한",
      pr_author: "sk88ee",
      pr_url: prUrl(28),
      change_type: "iac",
      risk_score: 87,
      risk_level: "CRITICAL",
      verdict: "REJECT",
      summary:
        "Lambda를 VPC에 배치하면서 egress를 10.0.0.0/8로 제한했으나 DynamoDB/STS 접근에 필요한 VPC Endpoint가 미구성되어 전체 Lambda 함수의 DynamoDB 연결이 차단될 위험이 있습니다. Globals.VpcConfig 일괄 적용으로 4개 Lambda가 동시에 영향을 받아 단일 배포 시 전체 API 순단이 우려됩니다. VPC Endpoint 추가 및 단계적 배포 계획 수립 후 재검토가 필요합니다.",
      code_block:
        `+Parameters:
+  VpcId:
+    Type: AWS::EC2::VPC::Id
+    Description: VPC that Lambda functions will attach to
+  PrivateSubnetIds:
+    Type: List<AWS::EC2::Subnet::Id>
+    Description: Private subnets for Lambda ENIs

 Globals:
   Function:
+    VpcConfig:
+      SecurityGroupIds:
+        - !Ref LambdaSecurityGroup
+      SubnetIds: !Ref PrivateSubnetIds

 Resources:
+  LambdaSecurityGroup:
+    Type: AWS::EC2::SecurityGroup
+    Properties:
+      GroupDescription: AIOps Lambda egress (locked down to internal CIDR)
+      VpcId: !Ref VpcId
+      SecurityGroupEgress:
+        - IpProtocol: tcp
+          FromPort: 443
+          ToPort: 443
+          CidrIp: 10.0.0.0/8
+          Description: HTTPS to internal services only
+        - IpProtocol: tcp
+          FromPort: 3306
+          ToPort: 3306
+          CidrIp: 10.0.0.0/8
+          Description: MySQL to RDS
+      SecurityGroupIngress: []
+      Tags:
+        - Key: Environment
+          Value: prod`,
      infra_impact:
        "sample-app/template.yaml 수정 (+42/-0). LambdaSecurityGroup 신규 생성(Replacement 없음), Globals.VpcConfig 추가로 4개 Lambda 함수 전체 VPC 재배치 발생. VPC Endpoint 미구성 시 DynamoDB/STS Public Endpoint 차단으로 전체 API 중단 위험.",
      issues: [
        {
          severity: "CRITICAL",
          title: "VPC Endpoint 미구성 — DynamoDB/STS Public Endpoint 차단",
          line_range: "template.yaml:L28-44",
          code: `SecurityGroupEgress:
  - IpProtocol: tcp
    FromPort: 443
    ToPort: 443
    CidrIp: 10.0.0.0/8
    Description: HTTPS to internal services only
# DynamoDB VPC Endpoint 없음 — Public Endpoint 접근 불가`,
          why:
            "VPC 배치 후 egress를 내부 CIDR로만 제한하면 DynamoDB/STS의 AWS Public Endpoint로의 경로가 차단되어 모든 Lambda 함수의 DB 호출이 즉시 실패합니다.",
          fix: `DynamoDBVpcEndpoint:
  Type: AWS::EC2::VPCEndpoint
  Properties:
    VpcId: !Ref VpcId
    ServiceName: !Sub com.amazonaws.\${AWS::Region}.dynamodb
    VpcEndpointType: Gateway
    RouteTableIds: [!Ref PrivateRouteTable]`,
        },
        {
          severity: "HIGH",
          title: "Globals.VpcConfig 일괄 적용 — 4개 Lambda 동시 영향",
          line_range: "template.yaml:L20-25",
          code: `Globals:
  Function:
    VpcConfig:
      SecurityGroupIds:
        - !Ref LambdaSecurityGroup
      SubnetIds: !Ref PrivateSubnetIds`,
          why:
            "Globals 섹션의 VpcConfig는 ListOrders, GetOrder, CreateOrder, GetProducts 4개 Lambda에 즉시 일괄 적용되어 단일 배포로 전체 서비스 API가 동시에 VPC로 이동합니다.",
        },
        {
          severity: "MEDIUM",
          title: "MySQL 3306 egress — 광범위 CIDR 허용 (RDS 미존재)",
          line_range: "template.yaml:L38-42",
          code: `  - IpProtocol: tcp
    FromPort: 3306
    ToPort: 3306
    CidrIp: 10.0.0.0/8
    Description: MySQL to RDS`,
          why:
            "현 템플릿에 RDS 리소스가 없는 상태에서 10.0.0.0/8 전체 대역의 3306 포트를 허용하는 것은 최소권한 원칙에 위배됩니다.",
          fix: `  - IpProtocol: tcp
    FromPort: 3306
    ToPort: 3306
    DestinationSecurityGroupId: !Ref RdsSecurityGroup
    Description: MySQL to RDS only`,
        },
        {
          severity: "LOW",
          title: "VPCAccessPolicy 권한 경계 미검증",
          line_range: "template.yaml:L77,L94,L114,L130",
          code: `Policies:
  - DynamoDBReadPolicy:
      TableName: !Ref OrdersTable
  - VPCAccessPolicy: {}`,
          why:
            "SAM 내장 VPCAccessPolicy는 ENI 생성/삭제 권한을 포함하며 서비스 계정의 Permission Boundary 정책과의 충돌 여부가 검토되지 않았습니다.",
        },
      ],
      developer_pattern:
        "sk88ee는 이 레포에서 IaC 리뷰 이력이 없는 신규 기여자입니다. Lambda VPC 배치 시 VPC Endpoint 의존성에 대한 추가 지식 공유를 권장합니다.",
      agent_persona: "InfraReviewer → invoke_security_agent → RiskJudge",
    },
  },
];

export function getScenario(id: string): Scenario | undefined {
  return scenarios.find((s) => s.id === id);
}
