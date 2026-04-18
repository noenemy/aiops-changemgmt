# Slack 템플릿 편집 가이드

Slack Block Kit 메시지를 외부 JSON 파일로 관리. 코드 배포 없이 템플릿 수정만으로 UI 변경 가능.

## 디렉토리 구조

```
slack_templates/
├── _renderer.py          # Mustache-lite 치환 엔진 (수정 불필요)
├── __init__.py
├── code_review.json      # 코드 리뷰 알림 (Webhook 경로)
├── infra_review.json     # 인프라 변경 알림 (Webhook 경로)
├── command_analysis.json # /analysis 응답
├── command_reject.json   # /reject 응답
├── command_fix.json      # /fix 응답
└── sections/             # 재사용 블록
    ├── pr_header.json
    ├── pr_fields.json
    ├── summary.json
    ├── issues_list.json
    ├── incident_match.json
    ├── developer_pattern.json
    ├── infra_impact.json
    └── footer.json
```

## 템플릿 문법

| 문법 | 의미 |
|------|------|
| `{{var}}` | `context[var]` 값 치환 (없으면 빈 문자열) — JSON safe escape 자동 |
| `{{#if var}}...{{/if}}` | `var` 값이 truthy일 때만 블록 포함 |
| `{{>sections/xxx}}` | 다른 JSON 파일을 그 자리에 include |

## 변수 사전

### 공통 (모든 템플릿)
| 변수 | 타입 | 설명 |
|------|------|------|
| `pr_number` | int | PR 번호 |
| `pr_title` | str | PR 제목 |
| `pr_author` | str | PR 작성자 |
| `pr_url` | str | PR URL |
| `agent_persona` | str | `CodeReviewer` / `InfraReviewer` / `RiskJudge` |
| `timestamp` | ISO8601 | 메시지 생성 시각 (자동) |

### 리뷰 결과 (code_review, infra_review, command_analysis)
| 변수 | 타입 | 설명 |
|------|------|------|
| `risk_score` | int | 0-100 |
| `risk_level` | enum | LOW / MEDIUM / HIGH / CRITICAL |
| `risk_emoji` | str | 🟢🟡🔴 (자동) |
| `verdict` | enum | APPROVE / REJECT |
| `verdict_label` | str | "✅ CI/CD 자동 실행" / "🚫 CI/CD 파이프라인 스킵" (자동) |
| `change_type` | enum | code / iac / mixed |
| `change_type_label` | str | "코드 리뷰" / "인프라 변경" (자동) |
| `summary` | str | 한국어 1-2문장 |
| `issues_text` | mrkdwn | 이슈 목록 (없으면 블록 생략) |
| `incident_match` | mrkdwn | 과거 장애 매칭 (없으면 블록 생략) |
| `developer_pattern` | mrkdwn | 개발자 패턴 설명 (없으면 블록 생략) |
| `infra_impact` | mrkdwn | 인프라 영향 (infra_review만, 없으면 블록 생략) |

### Slash Command 전용
| 변수 | 템플릿 | 설명 |
|------|--------|------|
| `actor` | command_reject, command_fix | 커맨드 실행자 (Slack user) |
| `reason` | command_reject | 거부 사유 |

## 새 템플릿 추가하기

1. `foo.json` 파일 생성
2. `post_slack_report` 호출 시 `{"template": "foo", ...}` 전달
3. 재사용 블록이 필요하면 `sections/`에 추가
4. Lambda 재배포 (템플릿은 Lambda 코드 번들 내부에 포함)

## 에러 처리

렌더링 실패 시 CloudWatch Logs에 `Template render failed (xxx): ...` 로그 + rendered raw JSON 출력. 변수 누락/오타를 이걸로 디버깅.

## 제약

- 블록 총 개수 ≤ 50 (Slack 제약)
- Section text ≤ 3000자, fields 요소 ≤ 10개
- Mustache-lite는 중첩 if를 지원하지만 루프(`{{#each}}`)는 **미지원** — 루프가 필요하면 호출 쪽에서 mrkdwn 문자열을 미리 조립해 `issues_text` 같은 단일 변수로 전달
