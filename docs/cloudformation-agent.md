# Bedrock Agent CloudFormation 템플릿

현재 Agent, Action Group Lambda, IAM Role은 CLI로 생성되어 있습니다.
아래는 동일한 리소스를 CloudFormation으로 재현하는 템플릿입니다.

> 주의: 현재 배포된 리소스를 이 템플릿으로 교체하면 Agent ID가 변경됩니다.
> 새 환경에 배포하거나, 기존 리소스를 삭제 후 사용하세요.

## 템플릿 위치

`infra/agent-template.yaml`
