/**
 * Live-execution API — streams stdout/stderr from an allowlisted command
 * as Server-Sent Events so the browser terminal can render them line-by-line.
 *
 * Only commands explicitly listed in ALLOWED_COMMANDS (per scenario id) are
 * executed. We pull the command definition from the shared scenarios file so
 * the frontend cannot inject arbitrary shell — it only passes a scenario id.
 *
 * The process is killed if the client disconnects.
 */

import { spawn } from "node:child_process";
import path from "node:path";

import { scenarios } from "@/data/scenarios";

const DEMO_RUN_SCRIPT = "tools/demo_run.py";

export const runtime = "nodejs";
// Disable caching — each run is a fresh stream.
export const dynamic = "force-dynamic";

// Repo root is two levels up from demo-console/src/app/api/run.
// next dev process.cwd() is demo-console/, so we climb one.
const REPO_ROOT = path.resolve(process.cwd(), "..");

// Only commands that start with one of these binaries are allowed.
// Scenarios defined in `scenarios.ts` currently use ./demo.sh and make.
const ALLOWED_BINS = new Set(["./demo.sh", "make", "python3"]);

function sseEvent(event: string, data: unknown): string {
  const body = typeof data === "string" ? data : JSON.stringify(data);
  return `event: ${event}\ndata: ${body}\n\n`;
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const scenarioId = url.searchParams.get("scenario") ?? "";
  const scenario = scenarios.find((s) => s.id === scenarioId);

  if (!scenario) {
    return new Response(sseEvent("error", { message: `Unknown scenario: ${scenarioId}` }), {
      status: 400,
      headers: { "Content-Type": "text/event-stream" },
    });
  }

  const { cmd, args, cwd } = scenario.liveCommand;
  if (!ALLOWED_BINS.has(cmd)) {
    return new Response(sseEvent("error", { message: `Command not allowed: ${cmd}` }), {
      status: 400,
      headers: { "Content-Type": "text/event-stream" },
    });
  }

  const workingDir = cwd ? path.resolve(REPO_ROOT, cwd) : REPO_ROOT;

  const encoder = new TextEncoder();

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      // Announce the command we're about to run (echoed in the terminal).
      controller.enqueue(
        encoder.encode(
          sseEvent("stdout", { text: `$ ${cmd} ${args.join(" ")}` }),
        ),
      );

      const child = spawn(cmd, args, {
        cwd: workingDir,
        env: {
          ...process.env,
          // tools/demo_run.py pulls the GitHub token from Secrets Manager
          // via this profile. Override with DEMO_AWS_PROFILE in .env.local
          // if needed.
          AWS_PROFILE: process.env.DEMO_AWS_PROFILE ?? process.env.AWS_PROFILE ?? "new-account",
          AWS_REGION: process.env.DEMO_AWS_REGION ?? process.env.AWS_REGION ?? "us-east-1",
          PYTHONUNBUFFERED: "1",
        },
        stdio: ["ignore", "pipe", "pipe"],
      });

      const pushChunk = (channel: "stdout" | "stderr") =>
        (chunk: Buffer) => {
          const text = chunk.toString("utf8");
          // Split on newlines so the terminal gets one event per line.
          for (const line of text.split(/\r?\n/)) {
            if (line.length === 0) continue;
            controller.enqueue(
              encoder.encode(sseEvent(channel, { text: line })),
            );
          }
        };

      child.stdout.on("data", pushChunk("stdout"));
      child.stderr.on("data", pushChunk("stderr"));

      child.on("error", (err) => {
        controller.enqueue(
          encoder.encode(sseEvent("error", { message: String(err) })),
        );
        controller.close();
      });

      child.on("close", (code) => {
        controller.enqueue(
          encoder.encode(sseEvent("done", { exitCode: code ?? -1 })),
        );
        controller.close();
      });

      // Abort handling: kill the child if the client disconnects.
      req.signal.addEventListener("abort", () => {
        if (!child.killed) child.kill("SIGTERM");
        controller.close();
      });
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}

// ── POST: close the demo PR for a scenario ─────────────────────────────
// Invoked by the Reset button in live mode so a subsequent Run can actually
// create a new PR (GitHub refuses a second open PR on the same head branch).
export async function POST(req: Request) {
  const url = new URL(req.url);
  const scenarioId = url.searchParams.get("scenario") ?? "";
  const action = url.searchParams.get("action") ?? "reset";
  const scenario = scenarios.find((s) => s.id === scenarioId);
  if (!scenario) {
    return Response.json(
      { ok: false, message: `Unknown scenario: ${scenarioId}` },
      { status: 400 },
    );
  }
  if (action !== "reset") {
    return Response.json(
      { ok: false, message: `Unsupported action: ${action}` },
      { status: 400 },
    );
  }

  const { stdout, stderr, code } = await runPython([
    DEMO_RUN_SCRIPT,
    "reset",
    scenarioId,
  ]);
  return Response.json(
    { ok: code === 0, exitCode: code, stdout, stderr },
    { status: code === 0 ? 200 : 500 },
  );
}

function runPython(args: string[]): Promise<{
  stdout: string;
  stderr: string;
  code: number;
}> {
  return new Promise((resolve) => {
    const child = spawn("python3", args, {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        AWS_PROFILE:
          process.env.DEMO_AWS_PROFILE ?? process.env.AWS_PROFILE ?? "new-account",
        AWS_REGION:
          process.env.DEMO_AWS_REGION ?? process.env.AWS_REGION ?? "us-east-1",
        PYTHONUNBUFFERED: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (c: Buffer) => (stdout += c.toString("utf8")));
    child.stderr.on("data", (c: Buffer) => (stderr += c.toString("utf8")));
    child.on("error", (err) => {
      resolve({ stdout, stderr: stderr + String(err), code: -1 });
    });
    child.on("close", (code) => {
      resolve({ stdout, stderr, code: code ?? -1 });
    });
  });
}
