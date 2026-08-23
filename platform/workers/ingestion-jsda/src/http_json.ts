/** JSON Response via Response.json. No Cache-Control (callers had none). */
export function json(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}
