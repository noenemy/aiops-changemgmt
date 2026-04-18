"""Inspect or clear AgentCore Memory entries for a repo.

Useful when tuning long-term summaries — purge stale summaries so the next
agent run starts fresh.
"""

from __future__ import annotations

import argparse
import os
import sys

import boto3


def get_memory_id(session: boto3.Session) -> str:
    cfn = session.client("cloudformation")
    outs = cfn.describe_stacks(StackName="aiops-changemgmt-agentcore")["Stacks"][0]["Outputs"]
    for o in outs:
        if o["OutputKey"] == "MemoryId":
            return o["OutputValue"]
    raise SystemExit("MemoryId output not found in agentcore stack")


def actor_for_repo(repo: str) -> str:
    return f"repo:{repo}"


def cmd_show(args, session: boto3.Session) -> None:
    c = session.client("bedrock-agentcore")
    memory_id = get_memory_id(session)
    actor = actor_for_repo(args.repo)

    sessions = c.list_sessions(memoryId=memory_id, actorId=actor, maxResults=20)
    print(f"Memory {memory_id}  actor={actor}  sessions={len(sessions.get('sessionSummaries', []))}")
    for s in sessions.get("sessionSummaries", []):
        sid = s["sessionId"]
        evs = c.list_events(memoryId=memory_id, actorId=actor, sessionId=sid, maxResults=5).get("events", [])
        print(f"\n  session={sid}  events={len(evs)}")
        for ev in evs:
            for p in ev.get("payload", []):
                conv = p.get("conversational", {})
                txt = conv.get("content", {}).get("text", "")[:200]
                if txt:
                    print(f"    [{conv.get('role','?')}] {txt}")


def cmd_clear(args, session: boto3.Session) -> None:
    c = session.client("bedrock-agentcore")
    memory_id = get_memory_id(session)
    actor = actor_for_repo(args.repo)

    sessions = c.list_sessions(memoryId=memory_id, actorId=actor, maxResults=50).get("sessionSummaries", [])
    if not sessions:
        print("No sessions to clear.")
        return
    print(f"Clearing {len(sessions)} sessions for actor={actor} ...")
    for s in sessions:
        try:
            c.delete_memory_record(memoryId=memory_id, memoryRecordId=s["sessionId"])
            print(f"  removed session {s['sessionId']}")
        except Exception as exc:
            print(f"  skip {s['sessionId']}: {exc}")


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    show = sub.add_parser("show")
    show.add_argument("--repo", required=True)
    clr = sub.add_parser("clear")
    clr.add_argument("--repo", required=True)
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE", "new-account"))
    p.add_argument("--region", default="us-east-1")
    args = p.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    (cmd_show if args.cmd == "show" else cmd_clear)(args, session)
    return 0


if __name__ == "__main__":
    sys.exit(main())
