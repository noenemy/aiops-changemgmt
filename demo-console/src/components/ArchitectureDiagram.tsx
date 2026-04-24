"use client";

import { useMemo } from "react";

import { AgentNode, HighlightedNode, getScenario } from "@/data/scenarios";

export type NodeState = "pending" | "active" | "done";

interface Props {
  // Kept from the legacy contract so page.tsx doesn't need to change.
  highlightPath: HighlightedNode[];
  nodeStates?: Record<string, NodeState>;
  scenarioId: string;
}

// Pyramid layout:
//   Top row    — GitHub ──► Strands Agent ──► Slack
//   Bottom row — Code · Security · Infra  (sub-agents fanned under Strands)
//
// Fits into 400×140 so the panel stays short vertically.
const LAYOUT: Record<AgentNode, { x: number; y: number; label: string; emoji: string }> = {
  github:   { x:  50, y:  30, label: "GitHub",   emoji: "🐙" },
  agent:    { x: 200, y:  30, label: "Strands",  emoji: "🤖" },
  slack:    { x: 350, y:  30, label: "Slack",    emoji: "💬" },
  code:     { x: 110, y: 110, label: "Code",     emoji: "💻" },
  security: { x: 200, y: 110, label: "Security", emoji: "🛡️" },
  infra:    { x: 290, y: 110, label: "Infra",    emoji: "🏗️" },
};

const NODE_W = 64;
const NODE_H = 34;

// Edges we animate. Source first, target second.
const EDGES: Array<[AgentNode, AgentNode]> = [
  ["github", "agent"],
  ["agent", "slack"],
  ["agent", "code"],
  ["agent", "security"],
  ["agent", "infra"],
];

export function ArchitectureDiagram({ highlightPath, nodeStates, scenarioId }: Props) {
  // Prefer the explicit agentPath if the scenario defined one. Otherwise
  // fall back to a reasonable guess from the legacy highlightPath so nothing
  // regresses in components that haven't been updated yet.
  const agentPath = useMemo<AgentNode[]>(() => {
    const s = getScenario(scenarioId);
    if (s?.agentPath?.length) return s.agentPath;
    // Minimal fallback — old scenarios without agentPath just show the
    // orchestrator, its code reviewer, and the Slack notification.
    return ["github", "agent", "code", "slack"];
  }, [scenarioId]);

  const onPath = useMemo(() => new Set(agentPath), [agentPath]);

  // Derive agent-node state from the legacy node-state map. The legacy
  // nodes mostly map to the architecture's "agent" node; we only want to
  // distinguish idle / running / done at the graph level.
  const overallState: "idle" | "running" | "done" = useMemo(() => {
    const states = Object.values(nodeStates ?? {});
    if (states.length === 0) return "idle";
    if (states.every((s) => s === "done")) return "done";
    if (states.some((s) => s === "active")) return "running";
    return "idle";
  }, [nodeStates]);

  // Per-agent-node state: everything on the path is either "active" or "done"
  // depending on overallState. Nodes off the path stay muted.
  const nodeStateFor = (n: AgentNode): "off" | "active" | "done" => {
    if (!onPath.has(n)) return "off";
    if (overallState === "done") return "done";
    // Even before the run starts we highlight the path faintly so viewers
    // can read which agents *would* be used. We treat idle as "done-muted"
    // visually — same colors but no pulse.
    if (overallState === "idle") return "done";
    return "active";
  };

  return (
    <div className="rounded-lg border border-white/10 bg-bg-panel p-4 overflow-visible">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs text-ink-muted font-mono">아키텍처 · 활성 경로</div>
        <Legend />
      </div>
      <svg
        viewBox="0 0 400 150"
        className="w-full h-auto arch-svg-host"
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          {/* Arrow head, rendered as a small SVG marker. Colored via
              currentColor so we can swap the stroke on the parent path. */}
          <marker
            id="arch-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" fill="currentColor" />
          </marker>

          {/* Soft glow for the active node. */}
          <filter id="arch-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Edges */}
        {EDGES.map(([from, to]) => {
          const a = LAYOUT[from];
          const b = LAYOUT[to];
          const active =
            onPath.has(from) && onPath.has(to) && overallState === "running";
          const done =
            onPath.has(from) && onPath.has(to) && overallState === "done";
          const idle =
            onPath.has(from) && onPath.has(to) && overallState === "idle";

          const cls = active
            ? "arch-edge active"
            : done
            ? "arch-edge done"
            : idle
            ? "arch-edge done muted"
            : "arch-edge off";

          // github→agent stays horizontal; every agent→sub-agent edge drops
          // vertically with a gentle S-curve so stacked targets read cleanly.
          const horizontal = Math.abs(a.y - b.y) < 10;
          const halfW = NODE_W / 2;
          const halfH = NODE_H / 2;
          const d = horizontal
            ? `M ${a.x + halfW} ${a.y} L ${b.x - halfW} ${b.y}`
            : (() => {
                const sx = a.x;
                const sy = a.y + halfH;
                const tx = b.x;
                const ty = b.y - halfH;
                const midY = (sy + ty) / 2;
                return `M ${sx} ${sy} C ${sx} ${midY}, ${tx} ${midY}, ${tx} ${ty}`;
              })();

          return (
            <g key={`${from}-${to}`}>
              <path d={d} className={cls} markerEnd="url(#arch-arrow)" />
              {active && (
                // A packet that travels along the path while the run is live.
                <circle r="3" className="arch-packet">
                  <animateMotion dur="1.4s" repeatCount="indefinite" path={d} />
                </circle>
              )}
            </g>
          );
        })}

        {/* Nodes */}
        {(Object.keys(LAYOUT) as AgentNode[]).map((id) => {
          const { x, y, label, emoji } = LAYOUT[id];
          const st = nodeStateFor(id);
          const cls = `arch-node ${st}`;
          const cx = NODE_W / 2;
          return (
            <g
              key={id}
              transform={`translate(${x - NODE_W / 2} ${y - NODE_H / 2})`}
              className={cls}
            >
              <rect
                width={NODE_W}
                height={NODE_H}
                rx="6"
                ry="6"
              />
              <text
                x={cx}
                y={13}
                textAnchor="middle"
                dominantBaseline="middle"
                className="arch-node-emoji"
              >
                {emoji}
              </text>
              <text
                x={cx}
                y={26}
                textAnchor="middle"
                dominantBaseline="middle"
                className="arch-node-label"
              >
                {label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function Legend() {
  return (
    <div className="flex items-center gap-3 text-[10px] font-mono text-ink-muted">
      <span className="flex items-center gap-1">
        <span className="w-2.5 h-2.5 rounded-sm bg-accent inline-block" />
        실행 중
      </span>
      <span className="flex items-center gap-1">
        <span className="w-2.5 h-2.5 rounded-sm bg-accent-green inline-block" />
        완료
      </span>
      <span className="flex items-center gap-1">
        <span className="w-2.5 h-2.5 rounded-sm border border-ink-muted/60 inline-block" />
        예정
      </span>
    </div>
  );
}
