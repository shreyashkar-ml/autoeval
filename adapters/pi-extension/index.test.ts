import assert from "node:assert/strict";
import test from "node:test";

import { autoexp } from "./bridge.ts";


test("reports a missing Autoexp runtime clearly", async () => {
  const original = process.env.PATH;
  process.env.PATH = "";
  try {
    await assert.rejects(
      autoexp(["agent", "context"], process.cwd()),
      /Autoexp CLI is not installed or not on PATH/,
    );
  } finally {
    process.env.PATH = original;
  }
});
