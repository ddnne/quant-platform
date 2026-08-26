import { base64ToBytes, bytesToBase64 } from "./canonical";

export type WrappedPrivateKey = {
  wrap_algorithm: "AES-GCM";
  wrap_iv_base64: string;
  wrapped_private_key_base64: string;
};

async function importWrappingKey(secret: string): Promise<CryptoKey> {
  if (!/^[0-9a-f]{64}$/.test(secret)) {
    throw new Error("receipt key wrapping secret is absent or invalid");
  }
  const bytes = Uint8Array.from(
    secret.match(/../g) ?? [],
    (pair) => Number.parseInt(pair, 16),
  );
  return crypto.subtle.importKey(
    "raw",
    bytes,
    { name: "AES-GCM", length: 256 },
    false,
    ["wrapKey", "unwrapKey"],
  );
}

export async function wrapEd25519PrivateKey(input: {
  privateKey: CryptoKey;
  wrappingSecret: string;
  aad: string;
}): Promise<WrappedPrivateKey> {
  if (
    input.privateKey.type !== "private" ||
    input.privateKey.algorithm.name !== "Ed25519" ||
    input.privateKey.extractable !== true
  ) throw new Error("receipt key generation did not produce a wrappable key");
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = new Uint8Array(await crypto.subtle.wrapKey(
    "pkcs8",
    input.privateKey,
    await importWrappingKey(input.wrappingSecret),
    {
      name: "AES-GCM",
      iv,
      additionalData: new TextEncoder().encode(input.aad),
      tagLength: 128,
    },
  ));
  return {
    wrap_algorithm: "AES-GCM",
    wrap_iv_base64: bytesToBase64(iv),
    wrapped_private_key_base64: bytesToBase64(ciphertext),
  };
}

export async function unwrapEd25519PrivateKey(input: {
  wrapped: WrappedPrivateKey;
  wrappingSecret: string;
  aad: string;
}): Promise<CryptoKey> {
  if (input.wrapped.wrap_algorithm !== "AES-GCM") {
    throw new Error("receipt authority wrapped key algorithm is invalid");
  }
  try {
    const key = await crypto.subtle.unwrapKey(
      "pkcs8",
      base64ToBytes(input.wrapped.wrapped_private_key_base64),
      await importWrappingKey(input.wrappingSecret),
      {
        name: "AES-GCM",
        iv: base64ToBytes(input.wrapped.wrap_iv_base64),
        additionalData: new TextEncoder().encode(input.aad),
        tagLength: 128,
      },
      { name: "Ed25519" },
      false,
      ["sign"],
    );
    if (
      key.type !== "private" || key.extractable !== false ||
      key.algorithm.name !== "Ed25519" ||
      key.usages.length !== 1 || key.usages[0] !== "sign"
    ) throw new Error("receipt authority operational private key invariant failed");
    return key;
  } catch (error) {
    if (
      error instanceof Error &&
      error.message === "receipt authority operational private key invariant failed"
    ) throw error;
    throw new Error("receipt authority wrapped key failed authenticated unwrap");
  }
}
