import { describe, expect, it } from "vitest";
import { hereForNext, safeNext, signInUrl } from "../../src/auth";

describe("sign-in: where to come back to", () => {
  it("only paths on this site", () => {
    expect(safeNext("/?page=setups")).toBe("/?page=setups");
    expect(safeNext("/api/scanner/report/x/index.html")).toBe("/api/scanner/report/x/index.html");
    for (const bad of ["https://evil.example/", "//evil.example", "/\\evil.example", "javascript:alert(1)", "", null, undefined]) {
      expect(safeNext(bad as string)).toBe("/");
    }
  });

  it("this page, without the sign-in's own parameters", () => {
    expect(hereForNext({ pathname: "/", search: "?symbol=NSE:TCS&tf=1h" })).toBe("/?symbol=NSE%3ATCS&tf=1h");
    expect(hereForNext({ pathname: "/", search: "?next=%2Fx&signin_error=y" })).toBe("/");
  });

  it("the sign-in link carries it", () => {
    expect(signInUrl("/?page=setups")).toBe("/api/auth/google/login?next=%2F%3Fpage%3Dsetups");
    expect(signInUrl("https://evil.example")).toBe("/api/auth/google/login?next=%2F");
  });
});
