import { expect, test as base, type APIRequestContext, type Page } from "@playwright/test";

export const API = "http://127.0.0.1:8010";
export const SYMBOL = "NSE:RELIANCE";

/** Put the shared backend back to a clean state: no drawings, alerts or custom indicators. */
export async function resetBackend(request: APIRequestContext) {
  for (const s of [SYMBOL, "NSE:TCS"]) {
    await request.put(`${API}/drawings?symbol=${encodeURIComponent(s)}`, { data: { items: [] } });
  }
  for (const a of await (await request.get(`${API}/alerts`)).json()) await request.delete(`${API}/alerts/${a.id}`);
  for (const c of await (await request.get(`${API}/custom-indicators`)).json()) {
    await request.delete(`${API}/custom-indicators/${c.id}`);
  }
}

export async function drawingCount(request: APIRequestContext, symbol = SYMBOL): Promise<number> {
  const r = await request.get(`${API}/drawings?symbol=${encodeURIComponent(symbol)}`);
  return (await r.json()).items.length;
}

/** Open the app with chosen saved settings (localStorage) and wait until the chart has data. */
export async function openApp(page: Page, storage: Record<string, unknown> = {}) {
  await page.addInitScript((s) => {
    if (sessionStorage.getItem("e2e-init")) return; // only on the first load: later reloads keep user changes
    sessionStorage.setItem("e2e-init", "1");
    localStorage.clear();
    for (const [k, v] of Object.entries(s)) localStorage.setItem(k, JSON.stringify(v));
  }, { symbol: SYMBOL, tf: "1D", patterns: [], ...storage });
  await page.goto("/");
  await expect(page.locator(".legend-row").first()).toContainText(/O\s*[\d,]+\.\d\d/); // OHLC legend filled
}

/** Fails the test on any uncaught page error (a crashed React render, a bad promise, ...). */
export const test = base.extend<{ pageErrors: string[] }>({
  pageErrors: [async ({ page }, use) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await use(errors);
    expect(errors, "uncaught errors in the page").toEqual([]);
  }, { auto: true }],
});
export { expect };
