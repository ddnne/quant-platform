import { denyTestOutbound } from "./test_outbound.mjs";

// Restore per-test stubs to this baseline, never to real acquisition/provider HTTP.
globalThis.fetch = denyTestOutbound;
