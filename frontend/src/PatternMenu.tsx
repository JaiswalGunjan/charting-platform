import type { PatternMeta } from "./api";

export const DEFAULT_PATTERNS = ["sr", "pp", "bbr", "wedge_pop", "cwh", "vcp"];

/** Checklist of chart patterns (rulebook rules), grouped, with how many were found on the current chart. */
export default function PatternMenu(props: {
  metas: PatternMeta[];
  enabled: string[];
  counts: Record<string, number>;
  onChange: (ids: string[]) => void;
}) {
  const { metas, enabled, counts } = props;
  const on = new Set(enabled);
  const groups = [...new Set(metas.map((m) => m.group))];
  const toggle = (id: string) => props.onChange(on.has(id) ? enabled.filter((x) => x !== id) : [...enabled, id]);
  const setGroup = (g: string, value: boolean) => {
    const ids = metas.filter((m) => m.group === g).map((m) => m.id);
    props.onChange(value ? [...new Set([...enabled, ...ids])] : enabled.filter((x) => !ids.includes(x)));
  };

  return (
    <div className="menu pattern-menu" onMouseDown={(e) => e.stopPropagation()}>
      <div className="pattern-actions">
        <b>Chart patterns</b>
        <span className="spacer" />
        <button className="small" onClick={() => props.onChange(metas.map((m) => m.id))}>All</button>
        <button className="small" onClick={() => props.onChange([])}>None</button>
        <button className="small" onClick={() => props.onChange(DEFAULT_PATTERNS)}>Defaults</button>
      </div>
      {groups.map((g) => {
        const ms = metas.filter((m) => m.group === g);
        const all = ms.every((m) => on.has(m.id));
        return (
          <div key={g}>
            <label className="menu-head pattern-group">
              <input type="checkbox" checked={all} onChange={() => setGroup(g, !all)} />
              {g}
            </label>
            {ms.map((m) => (
              <label key={m.id} className="pattern-item" title={`${m.about}\n\nRule: swingbt/rules/${m.rule.split(".")[0]}.py (${m.rule.split(".")[1] ?? ""})`}>
                <input type="checkbox" checked={on.has(m.id)} onChange={() => toggle(m.id)} />
                <span className="pattern-tag" style={{ background: m.color }}>{m.short || "S/R"}</span>
                <span className="grow">{m.title}</span>
                <span className={`small pattern-count${counts[m.id] ? "" : " zero"}`}
                  title={m.id === "sr" ? "levels on this chart" : "times it occurs in the loaded bars"}>
                  {counts[m.id] ?? "…"}
                </span>
              </label>
            ))}
          </div>
        );
      })}
      <div className="hint">Rules from your rulebook (TranscriptExtract/swingbt/rules), run on this chart's bars.
        Numbers = occurrences in the bars loaded on this chart, for every pattern (ticked or not). Markers sit on
        the signal bar; hover a bar for details. Designed for daily bars.</div>
    </div>
  );
}
