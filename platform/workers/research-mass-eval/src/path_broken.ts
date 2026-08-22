export function isPathBroken(
  evalPath: unknown,
  fallback?: unknown,
): boolean {
  const p = String(evalPath || "");
  const fb = String(fallback || "");
  if (p === "cs_generic" || p === "mdh_generic" || p === "unknown") return true;
  return fb.startsWith("path_broken") || fb.startsWith("mdh_empty");
}
