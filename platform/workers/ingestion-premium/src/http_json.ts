/** JSON Response via Response.json. No Cache-Control (neither caller had it). */
export function json(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}
