"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ArchitectureDiagram,
  NodeState,
} from "@/components/ArchitectureDiagram";
import { ScenarioPanel } from "@/components/ScenarioPanel";
import { SlackPreview } from "@/components/SlackPreview";
import { Terminal, TerminalMode } from "@/components/Terminal";
import { scenarios, HighlightedNode } from "@/data/scenarios";

type RunStatus = "idle" | "running" | "done" | "error";

type ResetState = "idle" | "closing" | "closed" | "failed";

export default function Page() {
  const [scenarioId, setScenarioId] = useState(scenarios[0].id);
  const [mode, setMode] = useState<TerminalMode>("scripted");
  const [runToken, setRunToken] = useState(0);
  const [showSlack, setShowSlack] = useState(false);
  const [status, setStatus] = useState<RunStatus>("idle");
  // Index into scenario.highlightPath for the "currently active" node.
  // -1 means nothing active (idle / pre-run).
  const [activeIdx, setActiveIdx] = useState(-1);
  // Only meaningful in live mode — tracks the PR-close round-trip.
  const [resetState, setResetState] = useState<ResetState>("idle");
  const [resetNote, setResetNote] = useState<string>("");

  const scenario = useMemo(
    () => scenarios.find((s) => s.id === scenarioId) ?? scenarios[0],
    [scenarioId],
  );

  const onRun = useCallback(() => {
    setShowSlack(false);
    setRunToken((n) => n + 1);
  }, []);

  // Local state reset only — used when switching scenario tabs where we
  // don't want to trigger a GitHub PR close.
  const resetLocal = useCallback(() => {
    setShowSlack(false);
    setRunToken(0);
    setStatus("idle");
    setActiveIdx(-1);
    setResetState("idle");
    setResetNote("");
  }, []);

  const onReset = useCallback(() => {
    setShowSlack(false);
    setRunToken(0);
    setStatus("idle");
    setActiveIdx(-1);

    // In live mode, also close the PR we just opened so the next Run can
    // actually create a new one (GitHub rejects two open PRs on the same
    // head branch). Scripted mode has nothing on GitHub to clean up.
    if (mode !== "live") {
      setResetState("idle");
      setResetNote("");
      return;
    }
    setResetState("closing");
    setResetNote("PR 닫는 중…");
    fetch(
      `/api/run?scenario=${encodeURIComponent(scenarioId)}&action=reset`,
      { method: "POST" },
    )
      .then(async (resp) => {
        const data = (await resp.json().catch(() => ({}))) as {
          ok?: boolean;
          stdout?: string;
          stderr?: string;
        };
        if (data.ok) {
          setResetState("closed");
          // Use the last non-empty line from the script for a concise hint.
          const last = (data.stdout ?? "")
            .split(/\r?\n/)
            .map((l) => l.trim())
            .filter(Boolean)
            .pop();
          setResetNote(last || "PR 닫힘.");
        } else {
          setResetState("failed");
          setResetNote(
            (data.stderr || data.stdout || "초기화 실패").split(/\r?\n/)[0],
          );
        }
      })
      .catch((err) => {
        setResetState("failed");
        setResetNote(`초기화 오류: ${String(err)}`);
      });
  }, [mode, scenarioId]);

  const onStatusChange = useCallback(
    (s: RunStatus) => {
      setStatus(s);
      // In live mode the real Slack message is posted to the actual channel
      // by the AgentCore pipeline — we don't have that data in the browser,
      // so keep the preview pane empty instead of showing scripted mock data.
      if (s === "done" && mode === "scripted") {
        setTimeout(() => setShowSlack(true), 400);
      }
    },
    [mode],
  );

  const onStepChange = useCallback((idx: number) => {
    setActiveIdx(idx);
  }, []);

  // Switching modes must reset any lingering scripted preview — the two modes
  // produce fundamentally different end states (mock vs. real).
  useEffect(() => {
    setShowSlack(false);
  }, [mode]);

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
                resetLocal();
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
          disabled={status === "running" || resetState === "closing"}
          className="px-4 py-2 rounded-md bg-accent text-[#0b1220] font-semibold text-sm hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          ▶ 실행
        </button>
        <button
          onClick={onReset}
          disabled={resetState === "closing"}
          className="px-4 py-2 rounded-md border border-white/15 text-sm text-ink hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          초기화
        </button>

        {mode === "live" && resetState !== "idle" && (
          <span
            className={[
              "text-xs font-mono",
              resetState === "closing" && "text-ink-muted",
              resetState === "closed" && "text-accent-green",
              resetState === "failed" && "text-accent-red",
            ]
              .filter(Boolean)
              .join(" ")}
            title={resetNote}
          >
            {resetState === "closing" && "⋯ 초기화 중"}
            {resetState === "closed" && `✓ ${resetNote}`}
            {resetState === "failed" && `✗ ${resetNote}`}
          </span>
        )}

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
                  {mode === "live"
                    ? "실전 모드 — 분석 결과는 실제 Slack 채널(#aiops-demo)에 게시됩니다."
                    : "실행이 완료되면 Slack 리포트가 여기에 표시됩니다."}
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
