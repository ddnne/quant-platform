/** Job-level candidate grade. Partial/unknown is false. Not GO. */

export function jobCandidateGrade(args: {
  n_expected: number;
  n_cells: number;
  n_complete: number;
  n_collapsed?: number;
  n_broken?: number;
}): boolean {
  const expected = Number(args.n_expected);
  if (!Number.isFinite(expected) || expected <= 0) return false;
  if (Number(args.n_cells) !== expected) return false;
  if (Number(args.n_complete) !== expected) return false;
  if (Number(args.n_collapsed || 0) > 0) return false;
  if (Number(args.n_broken || 0) > 0) return false;
  return true;
}
