# Slack App 설정 가이드

`/analysis`, `/reject`, `/fix` Slash Command를 활성화하는 설정.

## 1. Slack App 생성 (또는 기존 App 선택)

https://api.slack.com/apps 에서 기존 App을 선택하거나 새로 생성.

## 2. Bot 토큰 / 스코프

**OAuth & Permissions** → **Bot Token Scopes**에 추가:
- `chat:write` — 채널에 메시지 전송
- `commands` — Slash Command 등록

워크스페이스에 설치 후 **Bot User OAuth Token** (`xoxb-*`) 복사.

## 3. Signing Secret

**Basic Information** → **App Credentials** → **Signing Secret** 복사. 이 값으로 모든 요청이 HMAC-SHA256 서명됨.

## 4. Slash Commands 등록

**Slash Commands** → **Create New Command** 3번:

| Command | Request URL | Short Description | Usage Hint |
|---------|-------------|-------------------|------------|
| `/analysis` | `https://{API_ID}.execute-api.ap-northeast-2.amazonaws.com/prod/slack/commands` | PR 재분석 실행 | `[PR번호]` |
| `/reject` | (동일 URL) | 수동 REJECT + 코멘트 | `[PR번호] [사유]` |
| `/fix` | (동일 URL) | 수정 제안 생성 | `[PR번호]` |

`Escape channels, users, and links`는 체크하지 않음.

## 5. 워크스페이스 재설치

스코프나 커맨드를 추가한 뒤 **Install App → Reinstall to Workspace** 클릭.

## 6. AWS 측 시크릿 등록

CloudFormation 파라미터로 전달했다면 자동 저장됨. 나중에 변경할 때:
```bash
aws secretsmanager put-secret-value \
  --secret-id aiops-changemgmt-infra/slack-signing-secret \
  --secret-string <signing-secret>

aws secretsmanager put-secret-value \
  --secret-id aiops-changemgmt-infra/slack-bot-token \
  --secret-string <xoxb-token>
```

## 7. 동작 확인

Slack 채널에서:
```
/analysis 9
```
3초 이내에 `🔍 PR #9 재분석을 시작했습니다` ephemeral 응답이 오면 정상. 결과는 수십 초 내 채널에 게시됨.

에러 트러블슈팅:
- `dispatch_failed` 또는 timeout → Lambda 로그 확인
  ```
  aws logs tail /aws/lambda/aiops-changemgmt-infra-slack-command --since 2m --region ap-northeast-2
  ```
- `Invalid signature` → Signing Secret 불일치
- `unsupported command` → 커맨드 이름 오타

## 파라미터 개요

Slack이 POST하는 form-encoded body:
```
token=...&team_id=...&team_domain=...&channel_id=...&channel_name=...
&user_id=U123&user_name=ethan&command=%2Fanalysis&text=9
&response_url=...&trigger_id=...
```

`slack_command_handler`가 파싱해 Analysis Lambda에 다음 payload로 전달:
```json
{
  "command": "analysis",
  "pr_number": 9,
  "pr_title": "...",
  "pr_author": "...",
  "pr_url": "...",
  "actor": "ethan",
  "reason": ""
}
```
