# 테스트 가이드 (v3 / AgentCore)

실제 GitHub PR 생성이나 API Gateway 서명 검증을 우회하고, 배포된 파이프라인 끝단에 직접 페이로드를 흘려보내 테스트한다. Agent 프롬프트, 도구 로직, KB, Slack 템플릿을 반복 수정하면서 즉시 확인하는 게 목표.

---

## 0. 사전 조건

```bash
# AWS 프로파일 (기본값 new-account 가정)
export AWS_PROFILE=new-account

# GitHub PAT + Slack Bot Token은 한 번만 Secrets Manager 에 주입하면 재사용
aws secretsmanager put-secret-value --secret-id aiops-changemgmt-infra/github-token     --secret-string "ghp_..."     --region us-east-1
aws secretsmanager put-secret-value --secret-id aiops-changemgmt-infra/slack-bot-token  --secret-string "xoxb-..."    --region us-east-1

# 로컬 툴체인
python3 -m pip install --user --break-system-packages \
  bedrock-agentcore-starter-toolkit bedrock-agentcore strands-agents mcp boto3
export PATH="$HOME/Library/Python/3.13/bin:$PATH"   # agentcore CLI 경로

# Cognito client secret 은 .env.local 로 (gitignore 됨)
cat > .env.local <<'EOF'
COGNITO_SECRET=<Cognito user-pool client 의 client secret>
EOF
```

`.env.local` 이 없으면 Makefile 은 Secrets Manager (`aiops-changemgmt-cognito-client-secret`) 에서 자동 조회를 시도한다. 한 번 저장해 두면 `dev-agent` 가 알아서 읽는다.

대상 PR이 실제로 GitHub 에 열려 있어야 한다(Agent 가 `get_pr_diff` 로 호출). 리포는 기본 `noenemy/aiops-changemgmt`, 기본 PR 번호 `9`.

---

## 1. `make` 명령어 한눈에 보기

```bash
make help
```

| 카테고리 | 명령 | 설명 |
|---|---|---|
| Agent 재배포 | `make dev-agent` | Runtime(`agent/runtime/app.py`) 전체 재배포. 약 90초 |
|              | `make agent-status` | Runtime 상태/엔드포인트 출력 |
|              | `make agent-logs`   | Runtime CloudWatch 로그 tail (최근 5분) |
| Tool Lambda  | `make dev-tools`          | 5 종 Tool Lambda 전체 CFN 재배포 |
|              | `make dev-pr-tools`       | `pr_tools` 만 빠르게 zip 업데이트 (~3초) |
|              | `make dev-slack-tools`    | `slack_tools` 만 빠르게 zip 업데이트 |
| KB / Memory  | `make kb-sync`            | `infra/kb-data/` → S3 sync + Ingestion 재실행 |
|              | `make memory-show`        | 현재 레포의 장기 메모리 요약 출력 |
|              | `make memory-clear`       | 레포의 모든 세션 메모리 삭제 |
|              | `make dedup-clear`        | Tool dedup 테이블 비우기 (중복 방지 해제) |
| 트리거        | `make trigger PR=9`                   | PR opened 이벤트 시뮬레이션 (webhook) |
|              | `make trigger-analysis PR=9`          | `/analysis` 커맨드 |
|              | `make trigger-reject PR=9 REASON=..." ACTOR=...` | `/reject` 커맨드 |
|              | `make trigger-fix PR=9`               | `/fix` 커맨드 |
| Slack 템플릿 | `make slack-preview TEMPLATE=code_review` | 로컬 렌더 출력 (JSON blocks) |
|              | `make slack-post TEMPLATE=code_review`    | 렌더 후 실제 채널 포스트 |
| 정리          | `make pr-clean PR=9`                  | PR 의 bot 작성 코멘트 전부 삭제 |

인자는 전부 `PR=12`, `REASON="..."` 형태로 오버라이드.

---

## 2. 가장 자주 쓰는 테스트 루프

```bash
# 1) 깨끗한 상태로 초기화
make pr-clean PR=9
make dedup-clear

# 2) Agent 로직 수정
vi agent/runtime/app.py
make dev-agent                # ~90s

# 3) 트리거 → 백그라운드에서 파이프라인 실행
make trigger PR=9

# 4) 결과 확인 (아래 중 원하는 것)
make agent-logs               # Runtime 로그 마지막 5분
curl -s -H "Authorization: Bearer $GH_TOKEN" \
  "https://api.github.com/repos/noenemy/aiops-changemgmt/issues/9/comments?since=..."
# Slack 채널 #C0ASW5X99E1 확인
```

**파이프라인 체감 시간**: `trigger` 반환 ≈ 1초, 실제 GitHub 코멘트 / Slack 포스트까지 100~150초.

---

## 3. 시나리오별 테스트

### 3.1 Agent 프롬프트/로직 튜닝

바꾸는 파일: `agent/runtime/app.py` (시스템 프롬프트, Persona 규칙, Memory 로드 로직 등).

```bash
vi agent/runtime/app.py
make dev-agent
make pr-clean PR=9 && make dedup-clear
make trigger PR=9
make agent-logs
```

### 3.2 Tool Lambda 로직 수정

바꾸는 파일: `agent/tools/<name>/handler.py`. 5 종: `pr / ddb / kb / slack / subagent`.

```bash
vi agent/tools/kb/handler.py
make dev-tools                 # 전체 CFN 재배포
# 또는 특정 Lambda 만 빠르게
make dev-pr-tools
make dev-slack-tools
```

`common.py` 또는 `slack_templates/` 수정은 `make sync-common` (또는 dev-tools 가 자동 호출) 을 거친다.

### 3.3 KB (장애 이력 / 정책 / 런북) 업데이트

```bash
vi infra/kb-data/incidents/INC-0046-new-incident.md
make kb-sync                   # S3 업로드 + Ingestion 시작 (임베딩 완료까지 ~1-2분)
make trigger PR=9              # 새 KB 문서가 검색에 반영되는지 확인
```

### 3.4 Memory (장기 요약) 실험

```bash
make memory-show               # 레포 세션 요약 목록
make memory-clear              # 전부 삭제 (cold start 상태 재현)
make trigger PR=9              # 첫 실행 → Memory 비어있음
make trigger PR=9              # 두 번째 실행 → 이전 요약이 프롬프트에 주입됨
make memory-show               # 세션 요약이 쌓였는지 확인
```

### 3.5 Slack 템플릿 수정·비교

로컬 렌더(외부 호출 없음):

```bash
vi agent/slack_templates/code_review.json
make sync-common
make slack-preview TEMPLATE=code_review   # blocks JSON 출력
make slack-preview TEMPLATE=command_fix
```

실제 채널 포스트(빠른 비교용):

```bash
make slack-post TEMPLATE=code_review
make slack-post TEMPLATE=infra_review
```

여러 시나리오를 비교하려면:

```bash
python3 tools/slack_preview.py --template code_review \
  --overrides '{"risk_score":12,"risk_level":"LOW","verdict":"APPROVE"}' --post
python3 tools/slack_preview.py --template code_review \
  --overrides '{"risk_score":90,"risk_level":"CRITICAL","verdict":"REJECT"}' --post
```

Lambda 에 반영하려면 `make dev-slack-tools`.

### 3.6 `/reject`, `/fix` 등 Slack 커맨드 경로

```bash
make trigger-analysis PR=9                    # 재분석 (webhook 과 동일 경로)
make trigger-reject PR=9 REASON="보안 재검토" ACTOR=ethan   # Runtime 없이 바로 포스트
make trigger-fix PR=9                         # Fix 제안 파이프라인 (헤더 '🔧 AI Fix Suggestion')
```

각 커맨드가 실제 Slack 채널에서 어떻게 렌더되는지 확인할 수 있다.

---

## 4. 로그 / 디버깅

| 로그 그룹 | 의미 |
|---|---|
| `/aws/lambda/aiops-changemgmt-infra-analysis` | Runtime 진입점. `AGENT_RUNTIME_ARN` 호출 전후 |
| `/aws/bedrock-agentcore/runtimes/aiops_changemgmt_runtime-...-DEFAULT` | Runtime 자체. Strands 에이전트의 모든 tool 호출, 모델 출력 |
| `/aws/lambda/aiops-changemgmt-agentcore-pr-tools` | GitHub diff / comment |
| `/aws/lambda/aiops-changemgmt-agentcore-kb-tools` | KB retrieve |
| `/aws/lambda/aiops-changemgmt-agentcore-ddb-tools` | review-history / developer-profile |
| `/aws/lambda/aiops-changemgmt-agentcore-slack-tools` | Slack post_slack_report |
| `/aws/lambda/aiops-changemgmt-agentcore-subagent-tools` | DevOps/Security stub |

`make agent-logs` 외에 직접 tail:

```bash
aws logs tail /aws/lambda/aiops-changemgmt-agentcore-slack-tools --since 5m --format short --profile new-account --region us-east-1
```

Runtime 로그를 tool 호출 순서대로 보려면 `Tool #N:` 접두사 줄만 필터하면 된다.

---

## 5. 중복 호출 방지 (dedup) 이해

Runtime 이 동일 PR 을 여러 번 재실행하더라도 GitHub 코멘트·Slack 포스트는 **한 번만** 발생하도록, Tool Lambda 에서 DynamoDB 로 idempotency 를 보장한다.

- 테이블: `aiops-changemgmt-agentcore-tool-dedup`
- 키: `pr{pr_number}#{tool_name}` (Gateway 가 Runtime session id 를 전달하지 않으므로 PR 번호 기반)
- TTL: 24h 자동 만료

**같은 PR 로 연속 테스트할 때 반드시:**

```bash
make dedup-clear         # 그리고 make pr-clean PR=9
```

---

## 6. 리소스 식별자 치트시트

배포 후 ID 가 바뀌면 `Makefile` 상단 값 업데이트 필요.

```
Gateway URL:   https://aiops-changemgmt-gateway-c30ktnjtfk.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp
Memory ID:     aiops_changemgmt_memory-8yOyma7ILl
Runtime ARN:   arn:aws:bedrock-agentcore:us-east-1:336093158955:runtime/aiops_changemgmt_runtime-jj5rG36Uk4
KB ID:         J66IABOTH8
Slack channel: C0ASW5X99E1
Cognito:       domain=agentcore-c92b6d96, client=2ulgdak6e1t5dctbehtd8h1o52
```

CFN 스택 변경 후에는 스택 output 으로 재조회:

```bash
aws cloudformation describe-stacks --stack-name aiops-changemgmt-infra     --query "Stacks[0].Outputs"
aws cloudformation describe-stacks --stack-name aiops-changemgmt-agentcore --query "Stacks[0].Outputs"
```

---

## 7. 자주 맞닥뜨리는 함정

| 증상 | 원인 | 대응 |
|---|---|---|
| GitHub 코멘트가 여러 개 생김 | dedup 테이블이 비어있지 않거나 PR 번호 바뀜 | `make dedup-clear`, `make pr-clean PR=<num>` |
| Slack 메시지가 안 옴 | Bot Token placeholder, 채널에 앱 미초대, `chat:write` 권한 누락 | Secret 재주입 + 앱 초대 + scope 확인 |
| `Memory load skipped` | Memory 비어있으면 정상 (첫 실행). sessionId 에러는 코드 버그 | `make memory-show` 로 확인 |
| `AccessDenied` on agentcore S3 | 가끔 multipart 업로드가 간헐 실패. 재시도하면 성공 | `make dev-agent` 한 번 더 |
| `make dev-agent` 후 Runtime env 가 비어짐 | `--env` 를 전달하지 않은 경우 | Makefile 의 `dev-agent` 타겟은 env 를 명시 — 항상 make 경유로 배포 |
| Runtime 이 `template="standard"` 등 없는 템플릿 호출 | 프롬프트 반영 실패 | `slack_tools` 가 자동으로 `code_review`/`infra_review` 로 fallback |
