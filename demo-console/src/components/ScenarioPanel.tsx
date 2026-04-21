"use client";

import { Scenario } from "@/data/scenarios";

const SEVERITY_BADGE: Record<Scenario["severity"], string> = {
  LOW: "bg-accent-green/20 text-accent-green border-accent-green/30",
  MEDIUM: "bg-accent-yellow/20 text-accent-yellow border-accent-yellow/30",
  HIGH: "bg-accent-red/20 text-accent-red border-accent-red/30",
  CRITICAL: "bg-accent-red/30 text-accent-red border-accent-red/50",
};

export function ScenarioPanel({ scenario }: { scenario: Scenario }) {
  return (
    <div className="rounded-lg border border-white/10 bg-bg-panel p-5">
      <div className="flex items-center gap-2 mb-3">
        <span
          className={`px-2 py-0.5 rounded border text-[11px] font-mono ${SEVERITY_BADGE[scenario.severity]}`}
        >
          {scenario.severity}
        </span>
        <span className="px-2 py-0.5 rounded border border-white/10 text-[11px] font-mono text-ink-muted">
          {scenario.expectedVerdict}
        </span>
        {scenario.expectedKbMatch && (
          <span className="px-2 py-0.5 rounded border border-accent-blue/30 bg-accent-blue/10 text-[11px] font-mono text-accent-blue">
            KB: {scenario.expectedKbMatch}
          </span>
        )}
      </div>

      <h2 className="text-lg font-semibold text-ink">{scenario.title}</h2>
      <div className="mt-1 text-xs font-mono text-ink-muted">
        브랜치 · <span className="text-ink">{scenario.branch}</span>
      </div>
      <div className="mt-0.5 text-xs font-mono text-ink-muted">
        파일 · <span className="text-ink">{scenario.changedFile}</span>
      </div>

      <div className="mt-4">
        <div className="text-[11px] uppercase tracking-wider text-ink-muted mb-1">
          문제
        </div>
        <p className="text-sm text-ink leading-relaxed">{scenario.problem}</p>
      </div>

      <div className="mt-4">
        <div className="text-[11px] uppercase tracking-wider text-ink-muted mb-1">
          예상 결과
        </div>
        <p className="text-sm text-ink leading-relaxed">
          Risk Score <span className="font-bold">{scenario.slackPreview.risk_score}/100</span>,{" "}
          {scenario.expectedVerdict === "APPROVE"
            ? "파이프라인을 그대로 통과시킵니다."
            : "파이프라인을 차단하고 GitHub PR + Slack으로 근거를 공유합니다."}
        </p>
      </div>
    </div>
  );
}
