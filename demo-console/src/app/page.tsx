"use client";

import { useCallback, useMemo, useState } from "react";

import {
  ArchitectureDiagram,
  NodeState,
} from "@/components/ArchitectureDiagram";
import { ScenarioPanel } from "@/components/ScenarioPanel";
import { SlackPreview } from "@/components/SlackPreview";
import { Terminal, TerminalMode } from "@/components/Terminal";
import { scenarios, HighlightedNode } from "@/data/scenarios";

type RunStatus = "idle" | "running" | "done" | "error";

export default function Page() {
  const [scenarioId, setScenarioId] = useState(scenarios[0].id);
  const [mode, setMode] = useState<TerminalMode>("scripted");
  const [runToken, setRunToken] = useState(0);
  const [showSlack, setShowSlack] = useState(false);
  const [status, setStatus] = useState<RunStatus>("idle");
  // Index into scenario.highlightPath for the "currently active" node.
  // -1 means nothing active (idle / pre-run).
  const [activeIdx, setActiveIdx] = useState(-1);

  const scenario = useMemo(
    () => scenarios.find((s) => s.id === scenarioId) ?? scenarios[0],
    [scenarioId],
  );

  const onRun = useCallback(() => {
    setShowSlack(false);
    setRunToken((n) => n + 1);
  }, []);

  const onReset = useCallback(() => {
    setShowSlack(false);
    setRunToken(0);
    setStatus("idle");
    setActiveIdx(-1);
  }, []);

  const onStatusChange = useCallback((s: RunStatus) => {
    setStatus(s);
    if (s === "done") {
      setTimeout(() => setShowSlack(true), 400);
    }
  }, []);

  const onStepChange = useCallback((idx: number) => {
    setActiveIdx(idx);
  }, []);

  // Build per-node state from activeIdx + status.
  const nodeStates = useMemo<Record<string, NodeState>>(() => {
    const out: Record<string, NodeState> = {};
    const path = scenario.highlightPath;
    if (activeIdx < 0) {
      // Pre-run: everything pending.
      for (const n of path) out[n] = "pending";
      return out;
    }
    if (status === "done") {
      for (const n of path) out[n] = "done";
      return out;
    }
    path.forEach((node: HighlightedNode, i: number) => {
      if (i < activeIdx) out[node] = "done";
      else if (i === activeIdx) out[node] = "active";
      else out[node] = "pending";
    });
    return out;
  }, [activeIdx, status, scenario.highlightPath]);

  return (
    <div className="max-w-[1400px] mx-auto px-6 py-8">
      <Header />

      {/* Scenario tabs */}
      <div className="flex flex-wrap gap-2 mb-6">
        {scenarios.map((s) => {
          const active = s.id === scenarioId;
          return (
            <button
              key={s.id}
              onClick={() => {
                setScenarioId(s.id);
                onReset();
              }}
              className={[
                "px-3 py-1.5 rounded-md border text-sm font-mono transition",
                active
                  ? "bg-accent/10 border-accent text-accent"
                  : "border-white/10 text-ink-muted hover:text-ink hover:border-white/30",
              ].join(" ")}
            >
              {s.label}
            </button>
          );
        })}
      </div>

      {/* Top grid: description + diagram */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5 mb-5">
        <div className="lg:col-span-2">
          <ScenarioPanel scenario={scenario} />
        </div>
        <div className="lg:col-span-3">
          <ArchitectureDiagram
            scenarioId={scenario.id}
            highlightPath={scenario.highlightPath}
            nodeStates={nodeStates}
          />
        </div>
      </div>

      {/* Run controls */}
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <button
          onClick={onRun}
          disabled={status === "running"}
          className="px-4 py-2 rounded-md bg-accent text-[#0b1220] font-semibold text-sm hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          ▶ 실행
        </button>
        <button
          onClick={onReset}
          className="px-4 py-2 rounded-md border border-white/15 text-sm text-ink hover:bg-white/5"
        >
          초기화
        </button>

        <div className="ml-auto flex items-center gap-2 text-xs">
          <span className="text-ink-muted">모드</span>
          <ModeToggle mode={mode} onChange={setMode} />
        </div>
      </div>

      {/* Terminal + Slack preview */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        <div className="lg:col-span-3">
          <Terminal
            mode={mode}
            script={scenario.terminal}
            scenarioId={scenario.id}
            highlightPath={scenario.highlightPath}
            runToken={runToken}
            onStatusChange={onStatusChange}
            onStepChange={onStepChange}
          />
        </div>
        <div className="lg:col-span-2">
          {showSlack ? (
            <SlackPreview data={scenario.slackPreview} />
          ) : (
            <div className="rounded-lg border border-white/10 bg-bg-panel p-6 h-full flex items-center justify-center text-center">
              <div>
                <div className="text-4xl mb-3">💬</div>
                <div className="text-sm text-ink-muted">
                  실행이 완료되면 Slack 리포트가 여기에 표시됩니다.
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Header() {
  return (
    <header className="mb-8">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded bg-accent flex items-center justify-center text-[#0b1220] font-extrabold">
          AI
        </div>
        <div>
          <h1 className="text-xl font-bold text-ink">
            AIOps ChangeManagement — Demo Console
          </h1>
          <p className="text-xs text-ink-muted">
            AWS Seoul Summit 2026 · AI-Powered Cloud Ops · Bedrock AgentCore
          </p>
        </div>
      </div>
    </header>
  );
}

function ModeToggle({
  mode,
  onChange,
}: {
  mode: TerminalMode;
  onChange: (m: TerminalMode) => void;
}) {
  const option = (value: TerminalMode, label: string, hint: string) => {
    const active = mode === value;
    return (
      <button
        onClick={() => onChange(value)}
        title={hint}
        className={[
          "px-2.5 py-1 rounded border font-mono",
          active
            ? "bg-accent/15 border-accent text-accent"
            : "border-white/10 text-ink-muted hover:text-ink",
        ].join(" ")}
      >
        {label}
      </button>
    );
  };
  return (
    <div className="flex gap-1">
      {option("scripted", "연출", "미리 정의된 시나리오 출력 (안전, 오프라인)")}
      {option("live", "실제", "실제 ./demo.sh 실행 (네트워크 필요)")}
    </div>
  );
}
