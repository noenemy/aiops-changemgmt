"""Seed AgentCore Memory with synthetic past-review summaries for sk88ee.

The live agent calls _load_repo_memory(repo) at the start of each analysis to
pull a few recent session summaries for the same repo actor. By pre-writing
targeted fake summaries we give the model real context to cite ("sk88ee의
PR #7에서 동일 패턴 발견") during demos — matching the author profile lines
that already appear in the scripted Slack previews for H1/H3/I2.

Writes are idempotent by sessionId: rerunning the script produces a new
history entry with the same sessionId + timestamp, so clear via
tools/memory_ops.py if you need a reset.

Usage:
  python3 tools/memory_seed.py seed
  python3 tools/memory_seed.py seed --only h1
  python3 tools/memory_seed.py list
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import boto3

REPO = os.environ.get("GITHUB_REPO", "noenemy/aiops-changemgmt")
ACTOR = f"repo:{REPO}"

# Absolute timestamps for when each fake review happened. Pinned to the
# past so summaries don't appear to come from the future. Tweak freely —
# the agent only cares about the ordering.
#
# `session_suffix` becomes the sessionId; the live agent uses
# pr-<repo>-<pr_number>-<unix_ts> so we mirror that pattern.
FAKE_REVIEWS = {
    "h1": {
        "pr": 7,
        "ts": datetime(2026, 3, 4, 2, 30, tzinfo=timezone.utc),
        "summary": (
            "## PR #7 분석 완료 — 최종 요약\n\n"
            "### 🔴 판정: **HIGH REJECT** (Risk Score: 74/100)\n\n"
            "- PR: feat: 결제 서비스 초기 연동 스텁 (author: sk88ee)\n"
            "- 파일: sample-app/src/handlers/process_payment.py\n\n"
            "### 🚨 핵심 이슈\n"
            "1. HIGH — 외부 결제 서비스 API 키를 코드에 하드코딩 (sk_test_ 프리픽스, 주석 'TODO: 나중에 환경변수로')\n"
            "2. HIGH — INC-0045(2026-02-08, 결제 키 유출, ₩5M 손실) 패턴과 동일\n"
            "3. MEDIUM — requests.post timeout 미설정\n\n"
            "### 권고\n"
            "- Secrets Manager 로 이전 후 재요청. 동일 파일에 추가 변경 시 보안 리뷰 필수.\n"
            "- sk88ee: Secrets Manager 연동 가이드 미숙지 이력. 다음 결제 관련 PR 재발 가능성 높음."
        ),
    },
    "h3": {
        "pr": 5,
        "ts": datetime(2026, 2, 18, 7, 12, tzinfo=timezone.utc),
        "summary": (
            "## PR #5 분석 완료 — 최종 요약\n\n"
            "### 🔴 판정: **HIGH REJECT** (Risk Score: 68/100)\n\n"
            "- PR: refactor: get_orders 응답에 상품 가격 노출 (author: sk88ee)\n"
            "- 파일: sample-app/src/handlers/get_orders.py\n\n"
            "### 🚨 핵심 이슈\n"
            "1. HIGH — 루프 내 products 테이블 get_item 호출 (N+1 쿼리). 주문 50건 기준 51회 호출\n"
            "2. HIGH — scan() 사용, Limit/ExclusiveStartKey 미지정\n"
            "3. KB 매칭 — INC-0041(2025-12-20, 주문 API P99 8.4s, 매출 손실 ₩82M)과 코드 패턴 동일\n\n"
            "### 권고\n"
            "- batch_get_item 으로 재작성 후 재요청. 주문 목록 API 에서 scan 직접 호출 금지.\n"
            "- sk88ee: DynamoDB 가이드라인(scan 금지, 페이지네이션 필수) 온보딩 필요. 후속 주문 조회 PR 재발 우려."
        ),
    },
    "i2": {
        "pr": 8,
        "ts": datetime(2026, 3, 21, 5, 5, tzinfo=timezone.utc),
        "summary": (
            "## PR #8 분석 완료 — 최종 요약\n\n"
            "### 🟠 판정: **HIGH REJECT** (Risk Score: 62/100)\n\n"
            "- PR: chore(infra): Lambda 를 VPC 로 이동 (author: sk88ee)\n"
            "- 파일: sample-app/template.yaml\n\n"
            "### 🚨 핵심 이슈\n"
            "1. HIGH — Globals.VpcConfig 로 4개 Lambda 를 VPC 에 일괄 배치. VPC Endpoint 미구성 상태에서 Secrets Manager / STS / DynamoDB 접근 경로 단절 위험\n"
            "2. MEDIUM — LambdaSecurityGroup egress 가 0.0.0.0/0 으로 열려 있어 내부 CIDR 로 좁히려는 다음 PR 에서 장애 재현 가능성\n"
            "3. KB 매칭 — INC-0040(egress tightening, 2시간 장애) 선행 조건과 동일\n\n"
            "### 권고\n"
            "- DynamoDB Gateway Endpoint / Secrets Manager Interface Endpoint 를 먼저 생성하는 선행 PR 이후 재시도.\n"
            "- sk88ee: VPC 배치 시 control plane 접근 경로 의존성 미숙지. 후속 SG egress 축소 PR 시 동일 장애 재현 우려 — 강한 경고 필요."
        ),
    },
}


def _client(session: boto3.Session):
    return session.client("bedrock-agentcore")


def _memory_id(session: boto3.Session) -> str:
    cfn = session.client("cloudformation")
    outs = cfn.describe_stacks(StackName="aiops-changemgmt-agentcore")["Stacks"][0]["Outputs"]
    for o in outs:
        if o["OutputKey"] == "MemoryId":
            return o["OutputValue"]
    raise SystemExit("MemoryId output not found in agentcore stack")


def cmd_seed(args, session: boto3.Session) -> int:
    client = _client(session)
    memory_id = _memory_id(session)

    keys = [args.only] if args.only else list(FAKE_REVIEWS.keys())
    for k in keys:
        entry = FAKE_REVIEWS[k]
        ts_unix = int(entry["ts"].timestamp())
        session_id = f"pr-{REPO.replace('/', '-')}-{entry['pr']}-{ts_unix}"
        print(f"[{k}] seeding sessionId={session_id}")
        client.create_event(
            memoryId=memory_id,
            actorId=ACTOR,
            sessionId=session_id,
            eventTimestamp=ts_unix,
            payload=[{
                "conversational": {
                    "role": "ASSISTANT",
                    "content": {"text": entry["summary"][:2000]},
                }
            }],
        )
    print("Done.")
    return 0


def cmd_list(args, session: boto3.Session) -> int:
    client = _client(session)
    memory_id = _memory_id(session)
    sessions = client.list_sessions(
        memoryId=memory_id, actorId=ACTOR, maxResults=50,
    ).get("sessionSummaries", [])
    print(f"actor={ACTOR}  sessions={len(sessions)}")
    for s in sessions:
        print(f"  {s.get('sessionId')}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    seed = sub.add_parser("seed")
    seed.add_argument("--only", choices=sorted(FAKE_REVIEWS.keys()))
    sub.add_parser("list")
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE", "new-account"))
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = p.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    if args.cmd == "seed":
        return cmd_seed(args, session)
    if args.cmd == "list":
        return cmd_list(args, session)
    return 0


if __name__ == "__main__":
    sys.exit(main())
