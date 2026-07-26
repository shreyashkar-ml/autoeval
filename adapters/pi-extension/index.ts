import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { autoexp } from "./bridge.ts";

type State = { bindingId?: string; operationId?: string; sessionId?: string };
type Review = {
  operation_id: string;
  state: string;
  url?: string;
  experiment_id?: string;
  decision?: string | null;
  notes?: Array<{ scope: string; text: string }>;
};

export default function autoexpExtension(pi: ExtensionAPI) {
  let state: State = {};
  let poller: AbortController | undefined;
  const sessionID = (ctx: ExtensionContext) => ctx.sessionManager.getSessionId();
  const identity = (ctx: ExtensionContext) => [
    "--agent", "pi", "--session-id", sessionID(ctx), "--repo", ctx.cwd, "--json",
  ];
  const save = (next: State) => {
    state = { ...state, ...next };
    pi.appendEntry("autoexp-state", state);
  };

  async function wait(ctx: ExtensionContext, origin: string, operationID: string) {
    poller?.abort();
    const controller = new AbortController();
    poller = controller;
    try {
      const response = await autoexp(
        ["agent", "review", "wait", operationID, "--timeout", "3600", "--json"],
        ctx.cwd,
        controller.signal,
      );
      const review = response.data as Review;
      if (sessionID(ctx) !== origin) {
        ctx.ui.notify(`Autoexp review ${operationID} completed in another session; resume that session to deliver it.`, "warning");
        return;
      }
      if (review.state === "completed") {
        const message = review.decision === "approved" && !review.notes?.length
          ? "[AUTOEXP REVIEW COMPLETE]\nThe user approved the reviewed experiment without requesting changes. Do not open another review."
          : `[AUTOEXP REVIEW FEEDBACK]\nExperiment: ${review.experiment_id}\nOperation: ${operationID}\n\n${(review.notes ?? []).map(note => `- [${note.scope}] ${note.text}`).join("\n")}\n\nTreat these notes as the user's next instruction in the active Autoexp experiment.\nDo not open another review unless explicitly invoked.`;
        const claim = await autoexp(["agent", "delivery", operationID, "--json"], ctx.cwd);
        if ((claim.data as any).delivered) {
          pi.sendUserMessage(message, { deliverAs: "followUp" });
        }
      } else if (review.state === "dismissed") {
        ctx.ui.notify("Autoexp review closed without feedback.", "info");
        await autoexp(["agent", "delivery", operationID, "--json"], ctx.cwd);
      } else {
        ctx.ui.notify(`Autoexp review ended as ${review.state}.`, "warning");
      }
      save({ operationId: undefined });
      ctx.ui.setStatus("autoexp", undefined);
    } catch (error) {
      if (!controller.signal.aborted) {
        ctx.ui.notify(error instanceof Error ? error.message : String(error), "error");
        ctx.ui.setStatus("autoexp", undefined);
      }
    } finally {
      if (poller === controller) poller = undefined;
    }
  }

  pi.registerCommand("autoexp", {
    description: "Start or continue a reproducible Autoexp experiment",
    handler: async (args, ctx) => {
      try {
        const response = await autoexp([
          "agent", "context", ...identity(ctx), "--objective", args,
        ], ctx.cwd);
        const data = response.data as any;
        save({ bindingId: data.binding_id, sessionId: sessionID(ctx) });
        ctx.ui.setStatus("autoexp", data.experiment
          ? `autoexp: ${data.experiment.experiment_id.slice(0, 14)}`
          : "autoexp: experiment");
        pi.sendUserMessage(
          `[AUTOEXP PROTOCOL v1]\nBinding: ${data.binding_id}\nObjective: ${data.objective || "(not supplied)"}\nCommand prefix: ${data.exec_argv_prefix.join(" ")}\n\n${data.instruction}`,
          ctx.isIdle() ? undefined : { deliverAs: "followUp" },
        );
      } catch (error) {
        ctx.ui.notify(error instanceof Error ? error.message : String(error), "error");
      }
    },
  });

  pi.registerCommand("autoexp-review", {
    description: "Open Autoexp review for the active experiment",
    handler: async (args, ctx) => {
      if (!ctx.hasUI) {
        throw new Error("Autoexp review requires an interactive Pi session.");
      }
      if (poller) {
        ctx.ui.notify("An Autoexp review is already waiting in this session.", "warning");
        return;
      }
      try {
        const response = await autoexp([
          "agent", "review", "start", ...identity(ctx),
          ...(args.trim() ? ["--experiment", args.trim()] : []),
        ], ctx.cwd);
        const review = response.data as Review;
        const origin = sessionID(ctx);
        save({ operationId: review.operation_id, sessionId: origin });
        ctx.ui.setStatus("autoexp", "autoexp: review");
        ctx.ui.notify(`Autoexp review ready: ${review.url}`, "info");
        void wait(ctx, origin, review.operation_id);
      } catch (error) {
        ctx.ui.notify(error instanceof Error ? error.message : String(error), "error");
      }
    },
  });

  pi.on("session_start", async (_event, ctx) => {
    const entries = ctx.sessionManager.getEntries();
    const saved = [...entries].reverse().find(
      (entry: any) => entry.type === "custom" && entry.customType === "autoexp-state",
    ) as any;
    if (saved?.data) state = saved.data;
    try {
      const response = await autoexp(
        ["agent", "lifecycle", ...identity(ctx), "--event", "resume"],
        ctx.cwd,
      );
      const recovered = (response.data as any).review as Review | null;
      const operationID = state.sessionId === sessionID(ctx)
        ? state.operationId
        : recovered?.operation_id;
      if (operationID) {
        save({ operationId: operationID, sessionId: sessionID(ctx) });
        ctx.ui.setStatus("autoexp", "autoexp: review");
        void wait(ctx, sessionID(ctx), operationID);
      }
    } catch (error) {
      ctx.ui.notify(error instanceof Error ? error.message : String(error), "warning");
    }
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    poller?.abort();
    poller = undefined;
    ctx.ui.setStatus("autoexp", undefined);
    try {
      await autoexp(["agent", "lifecycle", ...identity(ctx), "--event", "shutdown"], ctx.cwd);
    } catch {}
  });

  pi.on("agent_end", (_event, ctx) => {
    if (!state.operationId) ctx.ui.setStatus("autoexp", undefined);
  });
}
