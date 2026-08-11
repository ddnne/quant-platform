import assert from "node:assert/strict";
import test from "node:test";
import { webcrypto } from "node:crypto";

if (!globalThis.crypto) globalThis.crypto = webcrypto;

import { signState, verifyState } from "../src/github-handler.js";

test("oauth state sign/verify round-trips AuthRequest payload", async () => {
  const secret = "test-state-secret";
  const req = {
    responseType: "code",
    clientId: "client-1",
    redirectUri: "https://chatgpt.com/connector/oauth/callback",
    scope: ["quant.read.ops"],
    state: "client-state",
    codeChallenge: "challenge",
    codeChallengeMethod: "S256",
  };
  const token = await signState(req, secret);
  const back = await verifyState(token, secret);
  assert.deepEqual(back, req);
});

test("oauth state rejects tampering", async () => {
  const secret = "test-state-secret";
  const token = await signState({ clientId: "a" }, secret);
  const tampered = token.slice(0, -4) + "xxxx";
  assert.equal(await verifyState(tampered, secret), null);
  assert.equal(await verifyState(token, "wrong-secret"), null);
});
