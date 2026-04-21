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
        env: process.env,
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
