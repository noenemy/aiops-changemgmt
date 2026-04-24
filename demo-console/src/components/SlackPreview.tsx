"use client";

import { SlackPreview as Data, SlackIssue, Severity } from "@/data/scenarios";

// Visual approximation of the real Slack Block Kit message produced by the
// AgentCore Runtime (code_review.json template). Keep the visible structure
// aligned with agent/slack_templates/* so the "연출" mode preview stays
// believable against actual Slack messages posted in "실전" mode.

const RISK_EMOJI: Record<Severity, string> = {
  LOW: "🟢",
  MEDIUM: "🟡",
  HIGH: "🔴",
  CRITICAL: "🔴",
};

const SEVERITY_EMOJI: Record<Severity, string> = {
  LOW: "🟢",
  MEDIUM: "🟡",
  HIGH: "🟠",
  CRITICAL: "🔴",
};

const CHANGE_TYPE_LABEL: Record<Data["change_type"], string> = {
  code: "코드 리뷰",
  iac: "인프라 변경",
  mixed: "코드 + 인프라",
};

// Matches agent/tools/slack/handler.py::_risk_bar — 10 boxes, colour by score.
function riskBar(score: number): string {
  const s = Math.max(0, Math.min(100, score | 0));
  const filled = Math.max(0, Math.min(10, Math.round(s / 10)));
  const box = s >= 81 ? "🟥" : s >= 51 ? "🟧" : s >= 21 ? "🟨" : "🟩";
  return box.repeat(filled) + "⬜".repeat(10 - filled);
}

export function SlackPreview({ data }: { data: Data }) {
  const verdictLabel =
    data.verdict === "APPROVE" ? "✅ CI/CD 자동 실행" : "🚫 CI/CD 파이프라인 스킵";
  const emoji = RISK_EMOJI[data.risk_level];

  return (
    <div className="rounded-lg border border-white/10 bg-[#1a1d21] text-[#d1d2d3] shadow-xl overflow-hidden">
      {/* Slack channel chrome */}
      <div className="flex items-center gap-2 px-4 py-2 bg-[#222529] border-b border-white/5">
        <div className="w-6 h-6 rounded bg-[#611f69] flex items-center justify-center text-white font-bold text-xs">
          #
        </div>
        <span className="text-sm font-medium">aiops-demo</span>
        <span className="ml-auto text-xs text-[#9a9b9e] font-mono">
          Slack preview
        </span>
      </div>

      <div className="px-4 py-3 text-sm">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded bg-accent flex items-center justify-center text-[#0b1220] font-bold text-xs shrink-0">
            AI
          </div>
          <div className="flex-1 min-w-0 space-y-2">
            {/* Author row */}
            <div className="flex items-baseline gap-2">
              <span className="font-semibold text-white">AIOps Agent</span>
              <span className="text-[11px] bg-[#2c2d30] text-[#9a9b9e] px-1 rounded">
                APP
              </span>
              <span className="text-[11px] text-[#9a9b9e]">방금</span>
            </div>

            {/* Header block: {{>sections/pr_header}} */}
            <div className="text-[15px] font-bold text-white">
              {emoji} PR #{data.pr_number} — {CHANGE_TYPE_LABEL[data.change_type]}
            </div>

            {/* PR fields: {{>sections/pr_fields}} */}
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
              <Field label="PR">
                <a
                  href={data.pr_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[#1d9bd1] hover:underline"
                >
                  {data.pr_title}
                </a>
              </Field>
              <Field label="Author">
                <span>{data.pr_author}</span>
              </Field>
            </div>

            {/* Risk bar: {{>sections/risk_bar}} */}
            <div className="text-[13px] leading-snug">
              <div>
                <span className="font-semibold text-white">Risk</span>{" "}
                <span className="tracking-tighter">{riskBar(data.risk_score)}</span>{" "}
                <span className="font-semibold text-white">
                  {data.risk_score}/100
                </span>{" "}
                · {data.risk_level}
              </div>
              <div>
                <span className="font-semibold text-white">판정</span>{" "}
                {verdictLabel}
              </div>
            </div>

            <Divider />

            {/* Summary */}
            {data.summary && (
              <div className="text-[13px]">
                <div className="font-semibold text-white">요약</div>
                <div className="mt-0.5 whitespace-pre-wrap">{data.summary}</div>
              </div>
            )}

            {/* Code block: {{>sections/code_block}} */}
            {data.code_block && (
              <div className="text-[13px]">
                <div className="font-semibold text-white">📄 변경된 코드 (핵심)</div>
                <CodeBlock text={data.code_block} diff />
              </div>
            )}

            {/* Per-issue items: {{#each issues}} {{>sections/issue_item}} */}
            {data.issues?.map((issue, i) => (
              <IssueItem key={i} issue={issue} index={i + 1} />
            ))}

            {/* Legacy text-only fallback */}
            {!data.issues && data.issues_text && (
              <div className="text-[13px]">
                <div className="font-semibold text-white">발견된 이슈</div>
                <div className="mt-0.5 whitespace-pre-wrap">{data.issues_text}</div>
              </div>
            )}

            {/* Infra impact (iac/mixed only) */}
            {data.infra_impact && (
              <>
                <Divider />
                <div className="text-[13px]">
                  <div className="font-semibold text-white">🔧 인프라 영향</div>
                  <div className="mt-0.5 whitespace-pre-wrap">
                    {data.infra_impact}
                  </div>
                </div>
              </>
            )}

            {/* Incident match — ONLY when the agent found a relevant one.
                Mirrors the `{{#if incident_code}}` gate in the template so
                mismatched 참고용 entries don't leak into the preview. */}
            {data.incident_match && data.incident_code && (
              <>
                <Divider />
                <div className="text-[13px]">
                  <div className="font-semibold text-white">⚠️ 과거 유사 장애</div>
                  <div className="mt-0.5">{data.incident_match}</div>
                  <CodeBlock text={data.incident_code} />
                  <div className="mt-1 italic text-[#9a9b9e]">
                    → 이번 PR 이 동일 패턴을 재도입
                  </div>
                </div>
              </>
            )}

            {/* Developer pattern */}
            {data.developer_pattern && (
              <>
                <Divider />
                <div className="text-[13px]">
                  <div className="font-semibold text-white">
                    👤 개발자 패턴
                  </div>
                  <div className="mt-0.5 whitespace-pre-wrap">
                    {data.developer_pattern}
                  </div>
                </div>
              </>
            )}

            <Divider />

            <div className="text-[11px] text-[#9a9b9e]">
              🤖 {data.agent_persona} · Bedrock AgentCore
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function IssueItem({ issue, index }: { issue: SlackIssue; index: number }) {
  return (
    <>
      <Divider />
      <div className="text-[13px]">
        <div className="font-semibold text-white">
          {SEVERITY_EMOJI[issue.severity]} 이슈 #{index} — {issue.severity}{" "}
          <span className="font-mono text-[#d1d2d3] bg-[#0f1115] px-1.5 py-0.5 rounded ml-1">
            {issue.title}
          </span>
          {issue.line_range && (
            <span className="italic text-[#9a9b9e] ml-1">
              ({issue.line_range})
            </span>
          )}
        </div>
        <CodeBlock text={issue.code} />
        <div className="mt-1">
          <span className="font-semibold text-white">왜 위험한가</span>:{" "}
          <span className="whitespace-pre-wrap">{issue.why}</span>
        </div>
        {issue.fix && (
          <div className="mt-1">
            <div className="font-semibold text-white">수정 제안</div>
            <CodeBlock text={issue.fix} />
          </div>
        )}
      </div>
    </>
  );
}

function CodeBlock({ text, diff = false }: { text: string; diff?: boolean }) {
  // Colour diff lines lightly. Stays close to Slack's own ``` rendering.
  const lines = text.split("\n");
  return (
    <pre className="mt-1 rounded bg-[#0f1115] border border-white/5 px-3 py-2 text-[12px] leading-[1.55] text-[#d1d2d3] overflow-x-auto whitespace-pre font-mono">
      {lines.map((l, i) => {
        let cls = "";
        if (diff) {
          if (l.startsWith("+")) cls = "text-accent-green";
          else if (l.startsWith("-")) cls = "text-accent-red";
        }
        return (
          <div key={i} className={cls}>
            {l || "\u00a0"}
          </div>
        );
      })}
    </pre>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 truncate">
      <span className="font-semibold text-white">{label}:</span>{" "}
      <span>{children}</span>
    </div>
  );
}

function Divider() {
  return <div className="my-2 border-t border-white/10" />;
}
