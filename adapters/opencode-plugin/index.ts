import type { Plugin } from "@opencode-ai/plugin";
import { autoexp, identity } from "./bridge.ts";

type Review = {
  operation_id: string;
  state: string;
  url?: string;
  notes?: Array<{ scope: string; text: string }>;
  decision?: string | null;
  experiment_id?: string;
  delivered?: boolean;
};

const AutoexpPlugin: Plugin = async ctx => {
  const sessions = new Set<string>();
  const pollers = new Map<string, AbortController>();
  const log = (level: "info" | "error", message: string) => {
    try {
      void ctx.client.app.log({
        body: { service: "autoexp", level, message },
      });
    } catch {}
  };

  const prompt = (sessionID: string, text: string) => ctx.client.session.prompt({
    path: { id: sessionID },
    body: { parts: [{ type: "text", text }] },
  });
  log("info", "Native adapter loaded.");

  const waitForReview = async (sessionID: string, operationID: string) => {
    if (pollers.has(sessionID)) return;
    const controller = new AbortController();
    pollers.set(sessionID, controller);
    try {
      const result = await autoexp(
        ["agent", "review", "wait", operationID, "--timeout", "3600", "--json"],
        ctx.directory,
        controller.signal,
      );
      const review = result.data as Review;
      if (review.state === "dismissed" || review.state === "canceled") {
        log("info", `Review ${review.state}: ${operationID}`);
        await autoexp(["agent", "delivery", operationID, "--json"], ctx.directory);
        return;
      }
      if (review.state !== "completed") {
        log("error", `Review ended as ${review.state}: ${operationID}`);
        return;
      }
      const message = review.decision === "approved" && !review.notes?.length
        ? "[AUTOEXP REVIEW COMPLETE]\nThe user approved the reviewed experiment without requesting changes. Do not open another review."
        : `[AUTOEXP REVIEW FEEDBACK]\nExperiment: ${review.experiment_id}\nOperation: ${operationID}\n\n${(review.notes ?? []).map(note => `- [${note.scope}] ${note.text}`).join("\n")}\n\nTreat these notes as the user's next instruction in the active Autoexp experiment.\nDo not open another review unless the user explicitly invokes the review command again.`;
      const claim = await autoexp(
        ["agent", "delivery", operationID, "--json"],
        ctx.directory,
      );
      if (!(claim.data as any).delivered) return;
      const response = await prompt(sessionID, message);
      const messageID = (response as any)?.data?.info?.id;
      await autoexp(
        ["agent", "delivery", operationID, ...(messageID ? ["--host-message-id", messageID] : []), "--json"],
        ctx.directory,
      );
    } catch (error) {
      if (!controller.signal.aborted) {
        log("error", error instanceof Error ? error.message : String(error));
      }
    } finally {
      if (pollers.get(sessionID) === controller) pollers.delete(sessionID);
    }
  };

  const resume = async (sessionID: string, event: "start" | "resume") => {
    if (sessions.has(sessionID)) return;
    sessions.add(sessionID);
    try {
      const response = await autoexp([
        "agent", "lifecycle", ...identity("opencode", sessionID, ctx.directory),
        "--event", event,
      ], ctx.directory);
      const review = (response.data as any).review as Review | null;
      if (review && !review.delivered) void waitForReview(sessionID, review.operation_id);
    } catch (error) {
      sessions.delete(sessionID);
      log("error", error instanceof Error ? error.message : String(error));
    }
  };

  const shutdown = async (sessionID: string, cancel = false) => {
    pollers.get(sessionID)?.abort();
    pollers.delete(sessionID);
    sessions.delete(sessionID);
    try {
      if (cancel) {
        const response = await autoexp([
          "agent", "lifecycle", ...identity("opencode", sessionID, ctx.directory),
          "--event", "resume",
        ], ctx.directory);
        const review = (response.data as any).review as Review | null;
        if (review?.state === "waiting") {
          await autoexp(["agent", "review", "cancel", review.operation_id, "--json"], ctx.directory);
        }
      }
      await autoexp([
        "agent", "lifecycle", ...identity("opencode", sessionID, ctx.directory),
        "--event", "shutdown",
      ], ctx.directory);
    } catch (error) {
      log("error", error instanceof Error ? error.message : String(error));
    }
  };

  return {
    event: async ({ event }: any) => {
      if (event.type === "session.created") {
        await resume(event.properties.info.id, "start");
      } else if (event.type === "session.updated") {
        await resume(event.properties.info.id, "resume");
      } else if (
        event.type === "session.error"
        && event.properties.sessionID
        && event.properties.error?.name === "MessageAbortedError"
      ) {
        await shutdown(event.properties.sessionID, true);
      } else if (event.type === "session.deleted") {
        await shutdown(event.properties.info.id);
      }
    },
    dispose: async () => {
      await Promise.all([...sessions].map(sessionID => shutdown(sessionID)));
    },
    "command.execute.before": async (input, output) => {
      if (input.command !== "autoexp" && input.command !== "autoexp-review") return;
      output.parts.length = 0;
      const sessionID = input.sessionID;
      sessions.add(sessionID);
      const rawArgs = input.arguments ?? "";

      try {
        if (input.command === "autoexp") {
          const response = await autoexp([
            "agent", "context", ...identity("opencode", sessionID, ctx.directory),
            "--objective", rawArgs,
          ], ctx.directory);
          const data = response.data as any;
          await prompt(sessionID,
            `[AUTOEXP PROTOCOL v1]\nBinding: ${data.binding_id}\nObjective: ${data.objective || "(not supplied)"}\nCommand prefix: ${data.exec_argv_prefix.join(" ")}\n\n${data.instruction}`,
          );
          return;
        }

        if (pollers.has(sessionID)) {
          log("error", "An Autoexp review is already waiting in this session.");
          return;
        }
        const experiment = rawArgs.trim();
        const response = await autoexp([
          "agent", "review", "start",
          ...identity("opencode", sessionID, ctx.directory),
          ...(experiment ? ["--experiment", experiment] : []),
        ], ctx.directory);
        const review = response.data as Review;
        log("info", `Review ready: ${review.url}`);
        void waitForReview(sessionID, review.operation_id);
      } catch (error) {
        log("error", error instanceof Error ? error.message : String(error));
      }
    },
  } as any;
};

export default AutoexpPlugin;
