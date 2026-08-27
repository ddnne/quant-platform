export type StrictJsonTopLevelValue =
  | { readonly kind: "array" | "boolean" | "number" | "object" }
  | { readonly kind: "null" }
  | { readonly kind: "string"; readonly value: string };

/**
 * Validate the entire JSON document while materializing only top-level
 * strings. Provider rows are shape-scanned, not passed through a second
 * whole-document JSON.parse. Duplicate keys include escape-equivalent names.
 */
class JsonShapeScanner {
  private index = 0;

  constructor(private readonly text: string) {}

  scanTopLevelObject(): ReadonlyMap<string, StrictJsonTopLevelValue> {
    this.skipWhitespace();
    if (this.text[this.index] !== "{") throw new SyntaxError("top-level object required");
    const values = this.object(true, 0);
    this.skipWhitespace();
    if (this.index !== this.text.length) throw new SyntaxError("trailing JSON");
    return values;
  }

  private skipWhitespace(): void {
    while (this.index < this.text.length) {
      const code = this.text.charCodeAt(this.index);
      if (code !== 0x09 && code !== 0x0a && code !== 0x0d && code !== 0x20) return;
      this.index += 1;
    }
  }

  private value(captureString: boolean, depth: number): StrictJsonTopLevelValue {
    if (depth > 128) throw new SyntaxError("JSON nesting limit");
    this.skipWhitespace();
    const char = this.text[this.index];
    if (char === "{") {
      this.object(false, depth + 1);
      return { kind: "object" };
    }
    if (char === "[") {
      this.array(depth + 1);
      return { kind: "array" };
    }
    if (char === '"') {
      const value = this.string(captureString, captureString ? 16_384 : null);
      return captureString ? { kind: "string", value } : { kind: "string", value: "" };
    }
    if (char === "t") {
      this.literal("true");
      return { kind: "boolean" };
    }
    if (char === "f") {
      this.literal("false");
      return { kind: "boolean" };
    }
    if (char === "n") {
      this.literal("null");
      return { kind: "null" };
    }
    this.number();
    return { kind: "number" };
  }

  private literal(expected: string): void {
    for (let offset = 0; offset < expected.length; offset += 1) {
      if (this.text[this.index + offset] !== expected[offset]) {
        throw new SyntaxError("invalid JSON literal");
      }
    }
    this.index += expected.length;
  }

  private number(): void {
    let index = this.index;
    if (this.text[index] === "-") index += 1;
    if (this.text[index] === "0") {
      index += 1;
      if (this.isDigit(this.text.charCodeAt(index))) throw new SyntaxError("leading zero");
    } else {
      if (!this.isNonZeroDigit(this.text.charCodeAt(index))) {
        throw new SyntaxError("invalid JSON number");
      }
      index += 1;
      while (this.isDigit(this.text.charCodeAt(index))) index += 1;
    }
    if (this.text[index] === ".") {
      index += 1;
      if (!this.isDigit(this.text.charCodeAt(index))) throw new SyntaxError("invalid fraction");
      while (this.isDigit(this.text.charCodeAt(index))) index += 1;
    }
    if (this.text[index] === "e" || this.text[index] === "E") {
      index += 1;
      if (this.text[index] === "+" || this.text[index] === "-") index += 1;
      if (!this.isDigit(this.text.charCodeAt(index))) throw new SyntaxError("invalid exponent");
      while (this.isDigit(this.text.charCodeAt(index))) index += 1;
    }
    this.index = index;
  }

  private isDigit(code: number): boolean {
    return code >= 0x30 && code <= 0x39;
  }

  private isNonZeroDigit(code: number): boolean {
    return code >= 0x31 && code <= 0x39;
  }

  private string(decode: boolean, maximumRawLength: number | null): string {
    const start = this.index;
    this.index += 1;
    while (this.index < this.text.length) {
      const code = this.text.charCodeAt(this.index);
      if (code === 0x22) {
        this.index += 1;
        if (!decode) return "";
        if (maximumRawLength !== null && this.index - start > maximumRawLength) {
          throw new SyntaxError("decoded JSON string limit");
        }
        const decoded: unknown = JSON.parse(this.text.slice(start, this.index));
        if (typeof decoded !== "string") throw new SyntaxError("invalid JSON string");
        return decoded;
      }
      if (code < 0x20) throw new SyntaxError("control character in JSON string");
      if (code === 0x5c) {
        this.index += 1;
        const escape = this.text[this.index];
        if (escape === "u") {
          for (let offset = 1; offset <= 4; offset += 1) {
            const hex = this.text.charCodeAt(this.index + offset);
            if (!((hex >= 0x30 && hex <= 0x39) ||
              (hex >= 0x41 && hex <= 0x46) || (hex >= 0x61 && hex <= 0x66))) {
              throw new SyntaxError("invalid JSON unicode escape");
            }
          }
          this.index += 5;
          continue;
        }
        if (!['"', "\\", "/", "b", "f", "n", "r", "t"].includes(escape ?? "")) {
          throw new SyntaxError("invalid JSON escape");
        }
      }
      this.index += 1;
    }
    throw new SyntaxError("unterminated JSON string");
  }

  private object(
    captureTopLevel: boolean,
    depth: number,
  ): ReadonlyMap<string, StrictJsonTopLevelValue> {
    this.index += 1;
    this.skipWhitespace();
    const keys = new Set<string>();
    const values = new Map<string, StrictJsonTopLevelValue>();
    if (this.text[this.index] === "}") {
      this.index += 1;
      return values;
    }
    while (true) {
      this.skipWhitespace();
      if (this.text[this.index] !== '"') throw new SyntaxError("object key required");
      const key = this.string(true, 4_096);
      if (keys.has(key)) throw new SyntaxError("duplicate JSON key");
      keys.add(key);
      this.skipWhitespace();
      if (this.text[this.index] !== ":") throw new SyntaxError("object colon required");
      this.index += 1;
      const value = this.value(captureTopLevel, depth);
      if (captureTopLevel) values.set(key, value);
      this.skipWhitespace();
      const delimiter = this.text[this.index];
      if (delimiter === "}") {
        this.index += 1;
        return values;
      }
      if (delimiter !== ",") throw new SyntaxError("object delimiter required");
      this.index += 1;
    }
  }

  private array(depth: number): void {
    this.index += 1;
    this.skipWhitespace();
    if (this.text[this.index] === "]") {
      this.index += 1;
      return;
    }
    while (true) {
      this.value(false, depth);
      this.skipWhitespace();
      const delimiter = this.text[this.index];
      if (delimiter === "]") {
        this.index += 1;
        return;
      }
      if (delimiter !== ",") throw new SyntaxError("array delimiter required");
      this.index += 1;
    }
  }
}

export function inspectStrictJsonObject(
  text: string,
): ReadonlyMap<string, StrictJsonTopLevelValue> {
  return new JsonShapeScanner(text).scanTopLevelObject();
}
