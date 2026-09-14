function digestBytes(digest: string): Uint8Array {
  const hex = digest.slice("sha256:".length);
  const bytes = new Uint8Array(32);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
}

export function checksumMatches(object: R2Object, digest: string): boolean {
  const actual = object.checksums?.sha256;
  if (!actual) return object.customMetadata?.sha256 === digest;
  const expected = digestBytes(digest);
  const actualBytes = new Uint8Array(actual);
  return (
    actualBytes.byteLength === expected.byteLength &&
    actualBytes.every((value, index) => value === expected[index])
  );
}

export function headMatches(
  object: R2Object,
  digest: string,
  size?: number,
): boolean {
  if (object.customMetadata?.sha256 && object.customMetadata.sha256 !== digest) {
    return false;
  }
  if (size !== undefined && object.size !== size) return false;
  return checksumMatches(object, digest);
}

/** Streaming create-only PUT shared by sidecar/panel children. */
export async function putStreamCreateOnly(
  bucket: R2Bucket,
  key: string,
  value: ReadableStream<Uint8Array>,
  options: {
    digest: string;
    contentType: string;
    size: number;
    customMetadata?: Record<string, string>;
  },
): Promise<"created" | "identical" | "conflict" | "checksum_rejected"> {
  const existing = await bucket.head(key);
  if (existing) {
    return headMatches(existing, options.digest, options.size)
      ? "identical"
      : "conflict";
  }
  let put: R2Object | null;
  try {
    put = await bucket.put(key, value, {
      httpMetadata: { contentType: options.contentType },
      customMetadata: {
        ...options.customMetadata,
        sha256: options.digest,
        immutable: "true",
      },
      sha256: digestBytes(options.digest),
      onlyIf: { etagDoesNotMatch: "*" },
    });
  } catch {
    return "checksum_rejected";
  }
  if (put !== null) return "created";
  const raced = await bucket.head(key);
  return raced && headMatches(raced, options.digest, options.size)
    ? "identical"
    : "conflict";
}
