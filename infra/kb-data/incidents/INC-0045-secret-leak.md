# 장애 보고서: INC-0045

## 개요
- **일시**: 2026-02-08 09:00 KST
- **심각도**: P1 (Critical) — 보안 인시던트
- **영향 시간**: 4시간 (시크릿 로테이션 완료까지)
- **비용**: 시크릿 로테이션 + 보안 감사 비용 ₩5,000,000

## 제목
결제 API 라이브 키가 소스코드에 하드코딩되어 Git 히스토리에 노출

## 증상
보안팀 정기 감사에서 결제 서비스의 라이브 API 키(`sk_live_*`)가
소스코드에 하드코딩된 것을 발견. Git 히스토리에 영구 기록되어 있었음.
추가로 DEBUG 로그에 카드 토큰이 평문으로 기록되고 있었음 (PCI DSS 위반).

## 근본 원인
개발자가 로컬 테스트 중 시크릿을 코드에 직접 입력하고, `TODO: 나중에 환경변수로 바꾸기` 코멘트를 남긴 채 PR을 올림.
리뷰어가 기능 로직에만 집중하여 시크릿 하드코딩을 놓침.
DEBUG 레벨 로그에 `card_token`이 f-string으로 포함되어 CloudWatch에 저장됨.

## 영향 받은 파일
- `src/handlers/process_payment.py`

## 코드 패턴 (문제)
```python
PAYMENT_API_KEY = "sk_live_a1b2c3d4e5f6"  # TODO: 나중에 환경변수로 바꾸기
logger.debug(f"Payment details: card={card_token}")
```

## 수정 방법
- AWS Secrets Manager에서 시크릿 로드
- 기존 키 즉시 폐기 및 로테이션
- 카드 토큰은 절대 로그에 포함 금지
- git-secrets + pre-commit hook 추가

## 재발 방지
- pre-commit hook에 시크릿 탐지 추가
- CI에서 자동 시크릿 스캔 (truffleHog, git-secrets)
- 로그 레벨 정책: DEBUG에서도 민감 데이터 금지
- PCI DSS 컴플라이언스 체크리스트 코드 리뷰 항목 추가

## 태그
secret-leak, hardcoded-credential, pci-dss, logging, card-token, process_payment
