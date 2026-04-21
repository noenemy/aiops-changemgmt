"use client";

import { SlackPreview as Data } from "@/data/scenarios";

// Visual approximation of Slack Block Kit. Not pixel-perfect — we prioritise
// making the risk/verdict legible on stage.

const RISK_EMOJI: Record<Data["risk_level"], string> = {
  LOW: "🟢",
  MEDIUM: "🟡",
  HIGH: "🔴",
  CRITICAL: "🔴",
};

const CHANGE_TYPE_LABEL: Record<Data["change_type"], string> = {
  code: "코드 리뷰",
  iac: "인프라 변경",
  mixed: "코드 + 인프라",
};

export function SlackPreview({ data }: { data: Data }) {
  const verdictLabel =
    data.verdict === "APPROVE" ? "✅ CI/CD 자동 실행" : "🚫 CI/CD 파이프라인 스킵";
  const emoji = RISK_EMOJI[data.risk_level];

  return (
    <div className="rounded-lg border border-white/10 bg-[#1a1d21] text-[#d1d2d3] shadow-xl overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2 bg-[#222529] border-b border-white/5">
        <div className="w-6 h-6 rounded bg-[#611f69] flex items-center justify-center text-white font-bold text-xs">
          #
        </div>
        <span className="text-sm font-medium">aiops-demo</span>
        <span className="ml-auto text-xs text-[#9a9b9e] font-mono">
          Slack preview
        </span>
      </div>

      <div className="px-4 py-3 space-y-3 text-sm">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded bg-accent flex items-center justify-center text-[#0b1220] font-bold text-xs shrink-0">
            AI
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2">
              <span className="font-semibold text-white">AIOps Agent</span>
              <span className="text-[11px] bg-[#2c2d30] text-[#9a9b9e] px-1 rounded">
                APP
              </span>
              <span className="text-[11px] text-[#9a9b9e]">방금</span>
            </div>

            {/* Header block */}
            <div className="mt-1 text-[15px] font-bold text-white">
              {emoji} PR #{data.pr_number} — {CHANGE_TYPE_LABEL[data.change_type]}
            </div>

            {/* PR fields */}
            <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
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
              <Field label="Risk">
                <span>
                  {emoji} {data.risk_score}/100 ({data.risk_level})
                </span>
              </Field>
              <Field label="판정">
                <span>{verdictLabel}</span>
              </Field>
            </div>

            <Divider />

            <Section title="요약" body={data.summary} />

            {data.issues_text && (
              <Section title="발견된 이슈" body={data.issues_text} />
            )}

            {data.infra_impact && (
              <Section title="🔧 인프라 영향" body={data.infra_impact} />
            )}

            {data.incident_match && (
              <Section title="⚠️ 과거 유사 장애" body={data.incident_match} />
            )}

            {data.developer_pattern && (
              <Section title="👤 개발자 패턴" body={data.developer_pattern} />
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 truncate">
      <span className="font-semibold text-white">{label}:</span>{" "}
      <span>{children}</span>
    </div>
  );
}

function Section({ title, body }: { title: string; body: string }) {
  return (
    <div className="mt-2 text-[13px]">
      <div className="font-semibold text-white">{title}</div>
      <div className="mt-0.5 whitespace-pre-wrap text-[#d1d2d3]">{body}</div>
    </div>
  );
}

function Divider() {
  return <div className="my-2 border-t border-white/10" />;
}
