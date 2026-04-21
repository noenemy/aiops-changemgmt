"use client";

import { useEffect, useRef, useState } from "react";

import { HighlightedNode, TerminalLine, scenarios } from "@/data/scenarios";
import {
  classifyLiveLine,
  deriveScriptedStepMap,
} from "@/data/stepHints";

export type TerminalMode = "scripted" | "live";

interface DisplayLine {
  kind: "prompt" | "stdout" | "stderr" | "info" | "success" | "warn";
  text: string;
}

interface TerminalProps {
  mode: TerminalMode;
  // A-mode: scripted playback
  script: TerminalLine[];
  // C-mode: live scenario id (passed to /api/run?scenario=...)
  scenarioId: string;
  // Highlighted architecture path (used to map step → node index).
  highlightPath: HighlightedNode[];
  // Bumping this re-triggers playback/execution from scratch.
  runToken: number;
  onStatusChange?: (status: "idle" | "running" | "done" | "error") => void;
  // Fires with the index into `highlightPath` that should be marked "active".
  // Values before this index are "done", values after are "pending".
  onStepChange?: (pathIndex: number) => void;
}

const KIND_CLASS: Record<DisplayLine["kind"], string> = {
  prompt: "text-accent",
  stdout: "text-ink",
  stderr: "text-accent-red",
  info: "text-accent-blue",
  success: "text-accent-green",
  warn: "text-accent-yellow",
};

function classifyStdout(text: string): DisplayLine["kind"] {
  if (/^\s*✓/.test(text) || /생성 완료|완료$/.test(text)) return "success";
  if (/^\s*⚠|WARN|경고/i.test(text)) return "warn";
  if (/^\s*(🔴|❌|ERROR|CRITICAL|REJECT)/i.test(text)) return "stderr";
  if (/^\s*→|^\s*Creating|^\s*Invoking/.test(text)) return "info";
  if (/^\s*\$/.test(text)) return "prompt";
  return "stdout";
}

// Strip ANSI escape sequences that demo.sh emits for colour.
const ANSI_RE = /\u001b\[[0-9;]*m/g;
const stripAnsi = (s: string) => s.replace(ANSI_RE, "");

export function Terminal({
  mode,
  script,
  scenarioId,
  highlightPath,
  runToken,
  onStatusChange,
  onStepChange,
}: TerminalProps) {
  const [lines, setLines] = useState<DisplayLine[]>([]);
  const [status, setStatus] = useState<"idle" | "running" | "done" | "error">(
    "idle",
  );
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeRef = useRef(0);

  useEffect(() => {
    onStatusChange?.(status);
  }, [status, onStatusChange]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  useEffect(() => {
    const myRunId = runToken;
    activeRef.current = myRunId;
    abortRef.current?.abort();
    abortRef.current = null;

    setLines([]);
    if (runToken === 0) {
      setStatus("idle");
      onStepChange?.(-1);
      return;
    }

    setStatus("running");
    onStepChange?.(0);

    if (mode === "scripted") {
      const stepMap = deriveScriptedStepMap(script, highlightPath);
      const cancelled = { v: false };

      // Enforce a minimum dwell time on each path index so the architecture
      // diagram's pulse is actually perceivable — a rapid-fire script can
      // otherwise race past active nodes in ~100ms.
      const MIN_DWELL_MS = 650;
      let lastEmittedPathIdx = -1;
      let lastEmittedAt = 0;
      const emitStep = (pathIdx: number) => {
        const now = performance.now();
        if (pathIdx === lastEmittedPathIdx) return;
        const delta = now - lastEmittedAt;
        const wait = Math.max(0, MIN_DWELL_MS - delta);
        setTimeout(() => {
          if (cancelled.v || activeRef.current !== myRunId) return;
          lastEmittedPathIdx = pathIdx;
          lastEmittedAt = performance.now();
          onStepChange?.(pathIdx);
        }, wait);
      };

      void playScript(
        script,
        (line) => {
          if (cancelled.v || activeRef.current !== myRunId) return;
          setLines((prev) => [...prev, line]);
        },
        (stepIdx) => {
          if (cancelled.v || activeRef.current !== myRunId) return;
          const pathIdx = stepMap[stepIdx];
          if (typeof pathIdx === "number") emitStep(pathIdx);
        },
      ).then(() => {
        if (!cancelled.v && activeRef.current === myRunId) {
          setStatus("done");
          onStepChange?.(highlightPath.length - 1);
        }
      });
      return () => {
        cancelled.v = true;
      };
    }

    // Live mode via SSE.
    const ac = new AbortController();
    abortRef.current = ac;
    let currentPathIdx = 0;

    // Real demo.sh output tails off after PR creation; the actual pipeline
    // then runs for ~90-120s in CloudWatch. To keep the diagram alive during
    // that quiet period we slowly advance the active node over an expected
    // duration, while still respecting hard jumps from matched keywords.
    const expectedSec =
      scenarios.find((s) => s.id === scenarioId)?.liveCommand.expectedSeconds ??
      100;
    const pathLen = highlightPath.length;
    const perNodeMs = Math.max(2500, (expectedSec * 1000) / Math.max(1, pathLen));
    const tickStart = performance.now();
    const timeBasedAdvance = setInterval(() => {
      if (activeRef.current !== myRunId) return;
      const elapsed = performance.now() - tickStart;
      // Don't crowd the last two nodes (they should land when we actually
      // see the `done` event from the server).
      const maxFromTime = Math.min(pathLen - 2, Math.floor(elapsed / perNodeMs));
      if (maxFromTime > currentPathIdx) {
        currentPathIdx = maxFromTime;
        onStepChange?.(currentPathIdx);
      }
    }, 700);

    runLive(
      scenarioId,
      ac.signal,
      (line, done, errored) => {
        if (activeRef.current !== myRunId) return;
        if (line) {
          setLines((prev) => [...prev, line]);
          const next = classifyLiveLine(line.text, highlightPath, currentPathIdx);
          if (next !== currentPathIdx) {
            currentPathIdx = next;
            onStepChange?.(currentPathIdx);
          }
        }
        if (errored) {
          setStatus("error");
          clearInterval(timeBasedAdvance);
        } else if (done) {
          setStatus("done");
          onStepChange?.(highlightPath.length - 1);
          clearInterval(timeBasedAdvance);
        }
      },
    ).catch((err) => {
      if (ac.signal.aborted) return;
      if (activeRef.current !== myRunId) return;
      setLines((prev) => [
        ...prev,
        { kind: "stderr", text: `연결 오류: ${String(err)}` },
      ]);
      setStatus("error");
      clearInterval(timeBasedAdvance);
    });

    return () => {
      ac.abort();
      clearInterval(timeBasedAdvance);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runToken]);

  return (
    <div className="flex flex-col rounded-lg border border-white/10 bg-[#05080f] shadow-xl overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2 bg-[#0a0f1c] border-b border-white/10">
        <div className="flex gap-1.5">
          <span className="w-3 h-3 rounded-full bg-accent-red/70" />
          <span className="w-3 h-3 rounded-full bg-accent-yellow/70" />
          <span className="w-3 h-3 rounded-full bg-accent-green/70" />
        </div>
        <span className="ml-2 text-xs text-ink-muted font-mono">
          demo · {mode === "live" ? "live" : "scripted"}
        </span>
        <span className="ml-auto text-xs font-mono">
          {status === "running" && (
            <span className="text-accent-yellow animate-pulseDot">● 실행 중</span>
          )}
          {status === "done" && <span className="text-accent-green">● 완료</span>}
          {status === "error" && <span className="text-accent-red">● 오류</span>}
          {status === "idle" && <span className="text-ink-muted">● 대기</span>}
        </span>
      </div>

      <div
        ref={scrollRef}
        className="px-4 py-3 h-[360px] overflow-y-auto font-mono text-[13px] leading-relaxed"
      >
        {lines.length === 0 ? (
          <div className="text-ink-muted italic">
            시나리오를 선택하고 [실행] 버튼을 누르세요.
          </div>
        ) : (
          lines.map((l, i) => (
            <div key={i} className={`whitespace-pre-wrap ${KIND_CLASS[l.kind]}`}>
              {l.text || "\u00a0"}
            </div>
          ))
        )}
        {status === "running" && (
          <span className="inline-block w-2 h-4 bg-accent-blue align-middle animate-caret" />
        )}
      </div>
    </div>
  );
}

// ── A-mode playback ──────────────────────────────────────────────────────
async function playScript(
  script: TerminalLine[],
  emit: (line: DisplayLine) => void,
  onStep: (index: number) => void,
) {
  const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

  for (let i = 0; i < script.length; i += 1) {
    const step = script[i];
    onStep(i);
    if (step.kind === "wait") {
      emit({ kind: "info", text: `⋯ ${step.label}` });
      const dots = 4;
      const each = Math.max(200, Math.floor(step.durationMs / dots));
      for (let d = 0; d < dots; d += 1) {
        await delay(each);
      }
      continue;
    }

    const pre = step.delayMs ?? defaultDelayFor(step.kind);
    await delay(pre);

    if (step.kind === "prompt") {
      await typewriter(step.text, (partial) => {
        emit({ kind: "prompt", text: partial });
      });
      continue;
    }
    emit({ kind: step.kind, text: step.text });
  }
}

function defaultDelayFor(kind: TerminalLine["kind"]): number {
  switch (kind) {
    case "prompt":
      return 250;
    case "info":
      return 200;
    case "success":
      return 250;
    case "warn":
    case "stderr":
      return 350;
    default:
      return 120;
  }
}

async function typewriter(
  text: string,
  onPartial: (partial: string) => void,
) {
  const totalMs = Math.min(500, 20 + text.length * 18);
  await new Promise((r) => setTimeout(r, totalMs));
  onPartial(text);
}

// ── C-mode live run via SSE ─────────────────────────────────────────────
async function runLive(
  scenarioId: string,
  signal: AbortSignal,
  emit: (line: DisplayLine | null, done: boolean, errored: boolean) => void,
) {
  const resp = await fetch(`/api/run?scenario=${encodeURIComponent(scenarioId)}`, {
    signal,
    headers: { Accept: "text/event-stream" },
  });
  if (!resp.ok || !resp.body) {
    throw new Error(`HTTP ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      emit(null, true, false);
      return;
    }
    buffer += decoder.decode(value, { stream: true });

    let sepIdx: number;
    while ((sepIdx = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, sepIdx);
      buffer = buffer.slice(sepIdx + 2);
      const parsed = parseSseEvent(rawEvent);
      if (!parsed) continue;

      if (parsed.event === "stdout" || parsed.event === "stderr") {
        const text = stripAnsi(parsed.data.text ?? "");
        const kind =
          parsed.event === "stderr" ? "stderr" : classifyStdout(text);
        emit({ kind, text }, false, false);
      } else if (parsed.event === "error") {
        emit(
          {
            kind: "stderr",
            text: `✗ ${parsed.data.message ?? "실행 중 오류"}`,
          },
          true,
          true,
        );
        return;
      } else if (parsed.event === "done") {
        const exit = parsed.data.exitCode ?? 0;
        if (exit === 0) {
          emit({ kind: "success", text: `✓ exit ${exit}` }, true, false);
        } else {
          emit({ kind: "stderr", text: `✗ exit ${exit}` }, true, true);
        }
        return;
      }
    }
  }
}

function parseSseEvent(raw: string): { event: string; data: any } | null {
  let event = "message";
  let dataStr = "";
  for (const line of raw.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
  }
  if (!dataStr) return null;
  try {
    return { event, data: JSON.parse(dataStr) };
  } catch {
    return { event, data: { text: dataStr } };
  }
}
