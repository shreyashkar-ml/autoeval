import { spawn } from "node:child_process";

export type Envelope<T = Record<string, unknown>> = {
  protocol_version: 1;
  ok: boolean;
  operation: string;
  data?: T;
  error?: { code: string; message: string };
};

export function autoexp(args: string[], cwd: string, signal?: AbortSignal): Promise<Envelope> {
  return new Promise((resolve, reject) => {
    const child = spawn("autoexp", args, { cwd, signal, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", chunk => { stdout += chunk; });
    child.stderr.on("data", chunk => { stderr += chunk; });
    child.on("error", error => reject(new Error(
      error.message.includes("ENOENT") ? "Autoexp CLI is not installed or not on PATH." : error.message,
    )));
    child.on("close", () => {
      try {
        const value = JSON.parse(stdout) as Envelope;
        if (value.protocol_version !== 1 || typeof value.ok !== "boolean") {
          throw new Error("unsupported protocol response");
        }
        if (!value.ok) throw new Error(`${value.error?.code ?? "autoexp_error"}: ${value.error?.message ?? "Unknown Autoexp error"}`);
        resolve(value);
      } catch (error) {
        reject(error instanceof SyntaxError
          ? new Error(`Autoexp returned malformed JSON${stderr ? `: ${stderr.trim()}` : "."}`)
          : error);
      }
    });
  });
}

export function identity(agent: string, sessionID: string, directory: string): string[] {
  return ["--agent", agent, "--session-id", sessionID, "--repo", directory, "--json"];
}
