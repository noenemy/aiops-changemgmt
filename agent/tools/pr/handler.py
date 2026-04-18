"""pr_tools Lambda — GitHub PR operations.

Tools:
  get_pr_diff(pr_number) -> string
  get_pr_files(pr_number) -> JSON list
  detect_change_type(pr_number) -> JSON {change_type, iac_files, code_files}
  post_github_comment(pr_number, comment_body) -> string ack
"""

import json
import os
import urllib.request

from common import claim_dedup, err, get_secret, ok, parse_event

GITHUB_TOKEN_SECRET_ARN = os.environ["GITHUB_TOKEN_SECRET_ARN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]

IAC_EXTS = (".yaml", ".yml", ".tf", ".tfvars")
IAC_PATH_HINTS = ("infra/", "terraform/", "cdk/", "k8s/", "kubernetes/", "helm/",
                  "chart.yaml", "kustomization.yaml")


def _gh(path: str, method: str = "GET", data: bytes | None = None,
        accept: str = "application/vnd.github.v3+json") -> str:
    token = get_secret(GITHUB_TOKEN_SECRET_ARN)
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": accept,
            "Content-Type": "application/json",
            "User-Agent": "AIOps-ChangeManagement",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode()


def get_pr_diff(pr_number: int) -> str:
    diff = _gh(f"/repos/{GITHUB_REPO}/pulls/{pr_number}",
               accept="application/vnd.github.v3.diff")
    if len(diff) > 15000:
        diff = diff[:15000] + "\n... (truncated)"
    return diff


def get_pr_files(pr_number: int) -> list:
    resp = _gh(f"/repos/{GITHUB_REPO}/pulls/{pr_number}/files")
    files = json.loads(resp)
    return [{"filename": f["filename"], "additions": f["additions"],
             "deletions": f["deletions"], "status": f["status"]} for f in files]


def detect_change_type(pr_number: int) -> dict:
    resp = _gh(f"/repos/{GITHUB_REPO}/pulls/{pr_number}/files")
    files = json.loads(resp)
    iac_files, code_files = [], []
    for f in files:
        fn = f["filename"].lower()
        if fn.endswith(IAC_EXTS) or any(h in fn for h in IAC_PATH_HINTS):
            iac_files.append(f["filename"])
        else:
            code_files.append(f["filename"])
    if iac_files and code_files:
        ctype = "mixed"
    elif iac_files:
        ctype = "iac"
    else:
        ctype = "code"
    return {"change_type": ctype, "iac_files": iac_files[:10], "code_files": code_files[:10]}


def post_github_comment(pr_number: int, comment_body: str) -> str:
    data = json.dumps({"body": comment_body}).encode()
    _gh(f"/repos/{GITHUB_REPO}/issues/{pr_number}/comments", method="POST", data=data)
    return f"Comment posted on PR #{pr_number}"


TOOLS = {
    "get_pr_diff": lambda a: get_pr_diff(int(a["pr_number"])),
    "get_pr_files": lambda a: get_pr_files(int(a["pr_number"])),
    "detect_change_type": lambda a: detect_change_type(int(a["pr_number"])),
    "post_github_comment": lambda a: post_github_comment(int(a["pr_number"]), a["comment_body"]),
}


def handler(event, context):
    tool, args, session_id = parse_event(event, context)
    fn = TOOLS.get(tool)
    if fn is None:
        return err(f"Unknown tool: {tool}")
    # Dedup key uses PR number when session_id is missing (Gateway doesn't
    # always pass it through client_context). This prevents duplicate comments
    # across retries within ~24h; pr-clean command is the reset handle.
    if tool == "post_github_comment":
        dedup_key = session_id or f"pr{args.get('pr_number', '?')}"
        if not claim_dedup(dedup_key, tool):
            return ok("Comment already posted (dedup skip)")
    try:
        return ok(fn(args))
    except KeyError as e:
        return err(f"Missing arg: {e}")
    except Exception as e:
        return err(f"Tool error: {e}", code=500)
