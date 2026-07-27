import assert from "node:assert/strict";
import test from "node:test";

import { identity } from "./bridge.ts";


test("builds a repository-bound native identity", () => {
  assert.deepEqual(identity("opencode", "session-1", "/repo"), [
    "--agent", "opencode", "--session-id", "session-1",
    "--repo", "/repo", "--json",
  ]);
});
