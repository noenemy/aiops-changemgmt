---
doc_type: policy
topic: iac-review-checklist
keywords: [iac, infrastructure, cloudformation, terraform, iam, security, cost, drift]
---

# 인프라 변경 리뷰 체크리스트

IaC(CloudFormation, Terraform, CDK, Kubernetes 매니페스트) 변경 시 아래 5축을 점검한다.

## 1. 리소스 영향 분석
- **Replacement 유발** — 변경이 기존 리소스 교체를 트리거하는가? (다운타임 발생 가능)
- **Delete 트리거** — RDS, DynamoDB, S3 버킷이 삭제 대상인가? 백업 확인
- **연쇄 영향** — Security Group, VPC, IAM 변경이 다른 스택에 영향 주는가?
- CloudFormation changeset을 먼저 생성해 영향 확인 권장

## 2. IAM / 권한
- `AdministratorAccess`, `*:*` 권한 금지
- 와일드카드 Resource(`"Resource": "*"`) 금지. 최소 ARN으로 제한
- 인라인 정책보다 관리형 정책 선호
- Service Role의 AssumeRole 주체 검증 — 외부 계정 허용 시 외부 ID 필수
- S3 버킷: PublicAccessBlock 유지, 버킷 정책 공개 허용 금지

## 3. 데이터 보존
- RDS/DynamoDB `DeletionPolicy: Retain` 또는 `Snapshot` 설정 확인
- S3 버킷 Versioning 및 MFA Delete
- 백업 정책 — PITR, 자동 백업, 백업 보존 기간

## 4. 비용
- 신규 비싼 리소스 등장 경고 — NAT Gateway, Aurora, ElastiCache, OpenSearch
- Provisioned Capacity vs On-Demand 적절성
- 불필요한 CloudWatch Log 보존 기간(무한 보존 금지, 30일 권장)
- 태그 누락 — 비용 배분 추적 불가

## 5. Drift / 의존성
- 의존 리소스 삭제 전에 의존자 먼저 삭제되었는가? (DependsOn)
- 콘솔에서 수동 변경된 리소스를 다시 IaC로 관리하려는 시도인가? → Drift 가능성
- 순환 의존성 — CloudFormation은 순환 의존 배포 불가

## 판정 기준
- Replacement 유발 + 데이터 보존 정책 없음 → CRITICAL (REJECT)
- IAM 과권한 또는 공개 노출 → HIGH (REJECT)
- 그 외는 MEDIUM/LOW 판정
