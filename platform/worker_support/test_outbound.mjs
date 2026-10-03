// Test-only default; explicit fixture transports and bindings remain available.
export async function denyTestOutbound() {
  throw new Error("Test HTTP disabled; inject or stub the transport");
}
