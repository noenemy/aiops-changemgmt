# Knowledge Base 데이터 편집 가이드

이 디렉토리는 Bedrock Knowledge Base의 원본 데이터다. 파일 편집/추가 후 S3로 동기화하면 자동 재인덱싱된다.

## 디렉토리 구조

```
kb-data/
├── incidents/       # 과거 장애 보고서 (P1/P2)
├── runbooks/        # 운영 가이드, 베스트 프랙티스
├── policies/        # 리뷰 정책 (code / iac)
└── deploy-history/  # 배포 통계 (KB 인덱싱 제외, 참고용)
```

## 파일 작성 규칙

### 1. 프론트매터 필수
모든 `.md` 파일 상단에 YAML 프론트매터를 넣는다. KB 메타데이터 필터링에 사용된다.

```markdown
---
doc_type: incident | runbook | policy
date: 2026-01-15          # incident만
severity: P1 | P2         # incident만
affected_files: [x.py]    # incident만
topic: api-change-policy  # runbook/policy만
keywords: [raca-condition, dynamodb, ...]  # 검색/필터용 — 영문+한글 혼용 가능
---
```

### 2. 파일명 규칙
- incidents: `INC-XXXX-short-description.md`
- runbooks: `topic-name.md`
- policies: `category_checklist.md`

### 3. 본문 구조 (자유)
헤딩(`##`)으로 섹션을 나누되, 검색 결과에 잘 매칭되도록 **키워드를 자연스럽게** 본문에 포함시킨다.

## 배포 방법

### 파일 추가/수정 후

```bash
# 1. S3 동기화 (자동 재인덱싱 트리거)
# deploy-history/는 참고용이라 S3에 올리지 않고 제외한다
aws s3 sync infra/kb-data/ s3://<kb-bucket>/ \
  --region ap-northeast-2 --delete \
  --exclude "deploy-history/*" --exclude "README.md"

# 2. 재인덱싱 확인 (몇 분 후)
aws logs tail /aws/lambda/<stack>-kb-reindex --since 5m --region ap-northeast-2
```

버킷 이름은 `aws cloudformation describe-stacks --stack-name aiops-changemgmt-infra --query 'Stacks[0].Outputs[?OutputKey==\`KBDataBucketName\`].OutputValue' --output text --region ap-northeast-2`로 확인.

### 파일 삭제

```bash
aws s3 sync infra/kb-data/ s3://<kb-bucket>/ \
  --region ap-northeast-2 --delete \
  --exclude "deploy-history/*" --exclude "README.md"
```

`--delete` 플래그가 로컬에서 삭제된 파일을 S3에서도 삭제한다.

## Agent에서의 활용

Agent는 Bedrock KB의 자동 도구 `queryKnowledgeBase`를 통해 이 데이터를 시맨틱 검색한다. 사용자는 도구를 직접 호출할 필요 없음 — Agent가 PR 분석 중 자동으로 검색한다.

예시 질의:
- `"재고 차감 race condition 관련 과거 장애"` → INC-0042 매칭
- `"N+1 쿼리 방지 가이드"` → runbook + INC-0041 매칭
- `"IAM AdministratorAccess 부여 정책"` → iac_review_checklist 매칭

## KB 인덱싱 제외

`deploy-history/`는 통계 데이터로 의미 검색에 부적합하므로 KB 인덱싱에서 제외된다. **실제 제외 방식은 S3 업로드 단계에서의 `--exclude` 필터** (위 명령어 참고). CloudFormation `InclusionPrefixes`는 초기 검증 단계에서 복수 prefix가 처리되지 않는 이슈가 있어 사용하지 않는다.
