# AIOps Change Management Demo

AI 기반 변경 관리 데모 — 코드 및 인프라 변경이 프로덕션에 배포되기 전에 리스크를 자동으로 감지하고 장애를 예방합니다.

이 데모는 AWS Seoul Summit 2026 컨퍼런스에서 AI-Powered Cloud Ops 부스의 데모를 위해 제작된 것입니다.

## 개요

개발자가 Pull Request를 생성하면 AI Agent가 변경 내용을 자동 분석하여 보안 취약점, 성능 저하, 데이터 손실 위험 등을 사전에 감지합니다. 분석 결과는 Slack 채널에 실시간으로 전달되며, 팀원들은 AI와 대화하며 리스크를 검토하고 배포 여부를 결정합니다.

## 아키텍처

```
개발자 → GitHub PR 생성
              │
              ▼
     GitHub Webhook → API Gateway → Lambda
                                      │
                                      ▼
                              AgentCore Agent
                             (ChangeManagement)
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                  ▼
              코드 분석          인프라 분석         이력 분석
           (Bedrock Claude)   (Bedrock Claude)   (DevOps Agent)
                    │                 │                  │
                    └─────────────────┼──────────────────┘
                                      ▼
                              Risk Score 산출
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
                    Low Risk                  High Risk
                   자동 승인                  배포 차단
                  → 배포 진행              → Slack 알림
                                           → 팀 리뷰 요청
                                           → 대화형 심층 분석
```

## 사용 서비스

| 서비스 | 역할 |
|--------|------|
| **Amazon Bedrock (Claude)** | 코드/인프라 변경 분석, 리스크 스코어링, 자연어 설명 생성 |
| **Amazon Bedrock AgentCore** | Slack 연동 에이전트 호스팅, MCP 서버로 GitHub·CloudWatch 도구 연결 |
| **AWS DevOps Agent** | 과거 장애 패턴 분석, 인시던트 상관관계 파악, 선제적 권고 |
| **Amazon QuickSight** | 변경 관리 대시보드 — 리스크 트렌드, 배포 메트릭 시각화 |
| **Kiro IDE** | 데모 애플리케이션 및 에이전트 코드 개발 |

## 프로젝트 구조

```
aiops-changemgmt/
├── sample-app/                  # 변경 대상 샘플 애플리케이션
│   ├── template.yaml            #   SAM 템플릿 (API GW + Lambda + DynamoDB)
│   ├── src/handlers/            #   Lambda 핸들러 (Orders/Products CRUD)
│   └── scripts/seed_data.py     #   샘플 데이터 시딩
├── agent/                       # Change Guardian AI Agent
│   ├── agent.py                 #   Strands Agent 정의
│   ├── mcp-servers/             #   MCP 서버 (GitHub, CloudWatch, DynamoDB)
│   └── prompts/                 #   시스템 프롬프트 및 분석 템플릿
├── webhook/                     # GitHub Webhook 수신 Lambda
│   └── handler.py
├── demo-scenarios/              # 데모용 사전 준비 PR 브랜치
│   ├── low-risk/                #   🟢 저위험: 응답 메시지 변경
│   ├── medium-risk/             #   🟡 중위험: Lambda 타임아웃 축소
│   └── high-risk/               #   🔴 고위험: DB 키 변경 + 메모리 축소 + SG 오픈
└── dashboard/                   # QuickSight 대시보드 설정
    └── dataset.json             #   샘플 리스크 분석 데이터
```

## 데모 시나리오

### Act 1: 안전한 변경 
저위험 코드 변경 PR → AI가 자동 분석 → Risk Score 12/100 → 자동 승인 → 배포 진행

### Act 2: 위험한 변경 감지 
고위험 변경 PR → AI가 3가지 Critical 이슈 감지 → 배포 차단 → Slack에서 대화형 심층 분석 → AI가 안전한 대안 PR 자동 생성

### Act 3: 장애 예방 인사이트 
Slack에서 "금요일 배포 리스크 분석해줘" 질문 → DevOps Agent가 과거 장애 패턴·트래픽·변경 규모 종합 분석 → 배포 일정 권고 → QuickSight 대시보드에서 메트릭 확인

## 시작하기

### 사전 요구사항

- AWS CLI 및 SAM CLI 설치
- Python 3.12+
- GitHub 계정 및 Personal Access Token
- Slack 워크스페이스 (Bot 생성 권한)
- Amazon Bedrock 모델 접근 권한 (Claude Sonnet)

### 1. 샘플 애플리케이션 배포

```bash
cd sample-app
sam build
sam deploy --guided --stack-name aiops-changemgmt-app
python scripts/seed_data.py --stack-name aiops-changemgmt-app
```

### 2. ChangeManagemet Agent 설정

```bash
cd agent
# AgentCore 에이전트 및 MCP 서버 배포 (가이드 추가 예정)
```

### 3. GitHub Webhook 연동

```bash
cd webhook
# Webhook 수신 Lambda 배포 및 GitHub 설정 (가이드 추가 예정)
```

### 4. Slack 연동

```bash
# Slack Bot 생성 및 AgentCore 연결 (가이드 추가 예정)
```

## 라이선스

MIT
