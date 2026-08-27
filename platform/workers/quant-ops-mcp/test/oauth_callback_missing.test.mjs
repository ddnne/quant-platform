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

test("OAuth state authority never falls back to the GitHub client secret", async () => {
  const provider = {
    parseAuthRequest: async () => ({ clientId: "client" }),
    completeAuthorization: async () => ({ redirectTo: "https://client.test" }),
  };
  const env = {
    GITHUB_CLIENT_ID: "github-client",
    GITHUB_CLIENT_SECRET: "provider-secret-is-not-a-state-key",
    ALLOWED_LOGIN: "allowed",
    OAUTH_PROVIDER: provider,
  };

  const authorize = await githubHandler.fetch(
    new Request("https://ops.test/authorize"),
    env,
  );
  assert.equal(authorize.status, 500);
  assert.equal(await authorize.text(), "server misconfigured: STATE_SECRET missing");

  const callback = await githubHandler.fetch(
    new Request("https://ops.test/callback?code=abc&state=legacy.invalid"),
    env,
  );
  assert.equal(callback.status, 500);
  assert.equal(await callback.text(), "server misconfigured: state secret unset");
});
