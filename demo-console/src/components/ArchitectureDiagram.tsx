"use client";

import { useEffect, useRef } from "react";
import mermaid from "mermaid";

import { HighlightedNode } from "@/data/scenarios";

export type NodeState = "pending" | "active" | "done";

interface Props {
  // All nodes that will be touched during the run.
  highlightPath: HighlightedNode[];
  // Per-node current state (pending / active / done). Optional — if omitted,
  // the whole path is rendered as `done` for static preview.
  nodeStates?: Record<string, NodeState>;
  // Re-render when scenario changes.
  scenarioId: string;
}

// Mermaid node ids → our semantic ids. Keep them 1:1 so highlight targeting
// is trivial in post-render CSS class manipulation.
const DIAGRAM = `
flowchart LR
  github[GitHub PR]:::ext
  slack[Slack]:::ext

  subgraph ingress[API Gateway]
    webhook[webhook Lambda]
    analysis[analysis Lambda]
  end

  subgraph agentcore[AgentCore - us-east-1]
    runtime[Strands Runtime<br/>3 Persona]
    memory[(Memory<br/>repo summary)]
    gateway[MCP Gateway]
    subgraph tools[Tool Lambdas]
      pr_tools[pr_tools]
      kb_tools[kb_tools]
      ddb_tools[ddb_tools]
      slack_tools[slack_tools]
    end
  end

  kb[(Bedrock KB<br/>S3 Vectors)]

  github --> webhook --> analysis --> runtime
  runtime <-.-> memory
  runtime --> gateway
  gateway --> pr_tools
  gateway --> kb_tools
  gateway --> ddb_tools
  gateway --> slack_tools
  kb_tools --> kb
  pr_tools --> github
  slack_tools --> slack
`;

// List of known node ids (must match the ids used in DIAGRAM above).
const NODE_IDS = [
  "github",
  "slack",
  "webhook",
  "analysis",
  "runtime",
  "memory",
  "gateway",
  "pr_tools",
  "kb_tools",
  "ddb_tools",
  "slack_tools",
  "kb",
] as const;

// Directed edges we care about animating. Must be kept in sync with DIAGRAM
// so that class assignment lines up with the actual <path> elements.
const EDGES: Array<[HighlightedNode, HighlightedNode]> = [
  ["github", "webhook"],
  ["webhook", "analysis"],
  ["analysis", "runtime"],
  ["runtime", "memory"],
  ["runtime", "gateway"],
  ["gateway", "pr_tools"],
  ["gateway", "kb_tools"],
  ["gateway", "ddb_tools"],
  ["gateway", "slack_tools"],
  ["kb_tools", "kb"],
  ["pr_tools", "github"],
  ["slack_tools", "slack"],
];

let mermaidInitialised = false;

export function ArchitectureDiagram({
  highlightPath,
  nodeStates,
  scenarioId,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    if (mermaidInitialised) return;
    mermaid.initialize({
      startOnLoad: false,
      theme: "dark",
      themeVariables: {
        background: "#0b1220",
        primaryColor: "#111a2e",
        primaryTextColor: "#e8ecf5",
        primaryBorderColor: "#334155",
        lineColor: "#475569",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: "14px",
      },
      securityLevel: "loose",
      flowchart: {
        curve: "basis",
        nodeSpacing: 40,
        rankSpacing: 60,
        padding: 14,
      },
    });
    mermaidInitialised = true;
  }, []);

  useEffect(() => {
    let cancelled = false;
    const render = async () => {
      const el = containerRef.current;
      if (!el) return;
      try {
        const { svg } = await mermaid.render(
          `arch-${scenarioId}-${Date.now()}`,
          DIAGRAM,
        );
        if (cancelled) return;
        el.innerHTML = svg;
        const svgEl = el.querySelector("svg");
        if (svgEl) {
          svgRef.current = svgEl as SVGSVGElement;
          tagNodesAndEdges(svgEl as SVGSVGElement);
          applyNodeStates(svgEl as SVGSVGElement, highlightPath, nodeStates);
        }
      } catch (err) {
        if (cancelled) return;
        el.innerHTML = `<pre class="text-accent-red text-xs p-4">${String(err)}</pre>`;
      }
    };
    void render();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId, highlightPath]);

  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    applyNodeStates(svgEl, highlightPath, nodeStates);
  }, [nodeStates, highlightPath]);

  return (
    <div className="rounded-lg border border-white/10 bg-bg-panel p-4 overflow-visible">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs text-ink-muted font-mono">
          아키텍처 · 활성 경로
        </div>
        <Legend />
      </div>
      <div ref={containerRef} className="min-h-[280px] arch-svg-host" />
    </div>
  );
}

// Tag node groups and edge paths with stable data attributes so we can
// target them later regardless of Mermaid's generated ids.
function tagNodesAndEdges(svgEl: SVGSVGElement) {
  // Nodes
  for (const id of NODE_IDS) {
    const g = svgEl.querySelector(
      `g.node[id^="flowchart-${id}-"]`,
    ) as SVGGElement | null;
    if (g) g.setAttribute("data-node", id);
  }

  // Edges — Mermaid v11 tags each edge path id as `L_from_to_idx`. We walk
  // our known EDGES array in order and match against the rendered paths.
  const edgePaths = Array.from(
    svgEl.querySelectorAll<SVGPathElement>("g.edgePaths path"),
  );

  for (const path of edgePaths) {
    const id = path.id || "";
    // id looks like "L_github_webhook_0" or "L-github-webhook-0".
    const m = id.match(/^L[_-]([^_-]+(?:_[^_-]+)*)[_-]([^_-]+(?:_[^_-]+)*)[_-]\d+$/)
      || id.match(/^L[_-](.+?)[_-](.+?)[_-]\d+$/);
    if (m) {
      path.setAttribute("data-from", m[1]);
      path.setAttribute("data-to", m[2]);
    }
  }
}

function applyNodeStates(
  svgEl: SVGSVGElement,
  highlightPath: HighlightedNode[],
  nodeStates?: Record<string, NodeState>,
) {
  // ── Nodes ───────────────────────────────────────────────────────────
  const allNodes = svgEl.querySelectorAll<SVGGElement>("g.node[data-node]");
  const stateById = new Map<string, NodeState | "off">();

  allNodes.forEach((g) => {
    const id = g.getAttribute("data-node")!;
    g.classList.remove("arch-on-path", "arch-active", "arch-done");

    if (!highlightPath.includes(id as HighlightedNode)) {
      stateById.set(id, "off");
      return;
    }

    const state = nodeStates?.[id] ?? "done";
    g.classList.add("arch-on-path");
    if (state === "active") g.classList.add("arch-active");
    else if (state === "done") g.classList.add("arch-done");
    stateById.set(id, state);
  });

  // ── Edges ───────────────────────────────────────────────────────────
  // An edge's state is derived from its endpoints:
  //   done   — both endpoints done
  //   active — edge is "entering" an active node (source done, target active)
  //   else   — dim
  const edgePaths = svgEl.querySelectorAll<SVGPathElement>(
    "g.edgePaths path[data-from]",
  );
  edgePaths.forEach((p) => {
    p.classList.remove("edge-done", "edge-active");
    const from = p.getAttribute("data-from")!;
    const to = p.getAttribute("data-to")!;
    const sFrom = stateById.get(from);
    const sTo = stateById.get(to);

    if (sFrom === "off" || sTo === "off") return;

    if (sFrom === "done" && sTo === "active") {
      p.classList.add("edge-active");
    } else if (sFrom === "done" && sTo === "done") {
      p.classList.add("edge-done");
    } else if (sFrom === "active" && sTo === "pending") {
      // Agent just started this branch — still show as active so the viewer
      // sees motion leading away from the current node.
      p.classList.add("edge-active");
    }
  });
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
