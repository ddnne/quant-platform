import assert from "node:assert/strict";
import test from "node:test";

import { githubHandler } from "../src/github-handler.js";

/** @param {string} search */
function getCallback(search) {
  return githubHandler.fetch(new Request(`https://ops.test/callback${search}`));
}

test("GET /callback without code/state is 400 missing code/state", async () => {
  const cases = ["", "?code=abc", "?state=xyz", "?code=", "?state=", "?code=&state="];
  for (const search of cases) {
    const res = await getCallback(search);
    assert.equal(res.status, 400, `search=${JSON.stringify(search)}`);
    assert.notEqual(res.status, 302);
    const raw = await res.text();
    assert.equal(raw, "missing code/state");
    assert.doesNotMatch(raw, /\bREADY\b/);
    assert.doesNotMatch(raw, /\bCOMPLETE\b/);
  }
});
