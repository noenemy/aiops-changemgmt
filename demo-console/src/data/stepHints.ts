// Helpers to derive which architecture node is "currently active" from
// ambient signals (scripted script index, or live stdout lines).

import { HighlightedNode, TerminalLine } from "@/data/scenarios";

// For the scripted mode, map each script step to the highlightPath index it
// should land on. Heuristic: look for keywords in the step text.
// Returns an array parallel to `script` where each entry is the
// highlightPath index that should be active *while that step plays*.
export function deriveScriptedStepMap(
  script: TerminalLine[],
  highlightPath: HighlightedNode[],
): number[] {
  const result: number[] = [];
  let idx = 0; // current position along highlightPath

  for (const step of script) {
    const text = stepText(step);
    const matchedIdx = matchPathIndex(text, highlightPath);
    if (matchedIdx !== null && matchedIdx >= idx) {
      idx = matchedIdx;
    } else {
      // Auto-advance based on step kind.
      const auto = autoAdvance(text, step.kind);
      if (auto !== null) {
        const mapped = highlightPath.indexOf(auto);
        if (mapped !== -1 && mapped >= idx) idx = mapped;
      }
    }
    result.push(idx);
  }
  return result;
}

function stepText(step: TerminalLine): string {
  if (step.kind === "wait") return step.label;
  return step.text;
}

// Map free-form strings to a known HighlightedNode by keyword. Returns the
// *best* matching node (deepest index along the pipeline so single keyword-
// rich lines advance further).
function matchPathIndex(
  text: string,
  highlightPath: HighlightedNode[],
): number | null {
  const keywords: [RegExp, HighlightedNode][] = [
    // Tool-level signals are strongest — check first.
    [/get_pr_diff|get_pr_files|detect_change_type|post_github_comment|pr-tools|pr_tools/i, "pr_tools"],
    [/query_?knowledge_?base|KB 조회|KB incidents|runbooks|policies|정책|kb-tools|kb_tools/i, "kb_tools"],
    [/get_review_history|get_developer_profile|review-history|개발자 프로파일|ddb-tools|ddb_tools/i, "ddb_tools"],
    [/post_slack_report|Slack 리포트 포스팅|slack-tools|slack_tools/i, "slack_tools"],
    [/Memory|세션 요약|가중치|memory/i, "memory"],
    [/INC-\d+|장애 매칭|유사 장애/i, "kb"],
    [/RiskJudge|CodeReviewer|InfraReviewer|Strands Runtime|Runtime 분석|Runtime 응답/i, "runtime"],
    [/Analysis Lambda|analysis Lambda|Runtime 호출 중/i, "analysis"],
    [/Webhook|webhook/i, "webhook"],
    [/Slack 리포트 전송 완료|Slack 채널/i, "slack"],
    [/GitHub PR 코멘트 작성 완료|PR #\d+ 생성/i, "github"],
  ];

  let best: number | null = null;
  for (const [re, node] of keywords) {
    if (re.test(text)) {
      const i = highlightPath.indexOf(node);
      if (i !== -1 && (best === null || i > best)) best = i;
    }
  }
  return best;
}

function autoAdvance(
  _text: string,
  _kind: TerminalLine["kind"],
): HighlightedNode | null {
  // Intentionally conservative — we don't want "generic success" lines to
  // leap the active node to the end of the path prematurely.
  return null;
}

// Live mode: classify a single stdout/stderr line into a pipeline index.
// Never moves backwards.
export function classifyLiveLine(
  text: string,
  highlightPath: HighlightedNode[],
  current: number,
): number {
  const idx = matchPathIndex(text, highlightPath);
  if (idx === null) return current;
  return Math.max(current, idx);
}
