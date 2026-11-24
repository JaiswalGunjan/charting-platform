import { describe, expect, it } from "vitest";
import type { PatternMeta } from "../../src/api";
import { filterPatterns } from "../../src/patternSearch";

const m = (id: string, title: string, short: string, group: string, summary = "", about = ""): PatternMeta =>
  ({ id, title, short, group, summary, about, color: "#000000", rule: "x.y" });

const metas = [
  m("cwh", "Cup with handle", "CWH", "Bases", "Breakout from a 4-26 week cup"),
  m("vcp", "VCP", "VCP", "Bases", "Breakout after ever-smaller pullbacks"),
  m("pp", "Pocket pivot", "PP", "Volume signals", "Up day whose volume beats every down day"),
  m("bbr", "Bad break recovery", "BBR", "Shapers", "Shakeout below the 50/21-day average", "then a follow-up pocket pivot"),
];
const ids = (q: string) => filterPatterns(metas, q).map((x) => x.id);

describe("pattern menu search", () => {
  it("empty or blank search lists everything", () => {
    expect(ids("")).toEqual(["cwh", "vcp", "pp", "bbr"]);
    expect(ids("   ")).toEqual(["cwh", "vcp", "pp", "bbr"]);
  });
  it("matches name, marker text and group, case-insensitively", () => {
    expect(ids("cup")).toEqual(["cwh"]);
    expect(ids("vcp")).toEqual(["vcp"]);
    expect(ids("BASES")).toEqual(["cwh", "vcp"]);
  });
  it("also matches the plain-English description and the rule text", () => {
    expect(ids("shakeout")).toEqual(["bbr"]);
    expect(ids("pocket pivot")).toEqual(["pp", "bbr"]);   // BBR's rule mentions a follow-up pocket pivot
  });
  it("no match gives an empty list", () => expect(ids("zzz")).toEqual([]));
});
