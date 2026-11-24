import type { PatternMeta } from "./api";

/** Patterns menu search: matches the name, marker text (VCP, BBR...), group, id, description or summary. */
export function filterPatterns(metas: PatternMeta[], q: string): PatternMeta[] {
  const ql = q.trim().toLowerCase();
  if (!ql) return metas;
  return metas.filter((m) =>
    [m.title, m.short, m.group, m.id, m.about, m.summary ?? ""].some((x) => x.toLowerCase().includes(ql)));
}
