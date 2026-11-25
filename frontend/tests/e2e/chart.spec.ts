import { expect, openApp, resetBackend, test } from "./fixtures";

test.beforeEach(async ({ request }) => resetBackend(request));

test("app loads: chart, quote, live badge, watchlist; attribution on the About page", async ({ page }) => {
  await openApp(page);
  await expect(page.locator(".legend-row").first()).toContainText("NSE:RELIANCE");
  await expect(page.locator(".legend-row").first()).toContainText("· 1D");
  await expect(page.locator(".chart canvas").first()).toBeVisible();
  await expect(page.locator(".quote b")).toHaveText(/[\d,]+\.\d\d/);
  await expect(page.locator(".conn")).toContainText(/Simulated ticks|Live|Last close/);
  await expect(page.locator(".wl tbody tr").first()).toBeVisible();
  // the TradingView logo at the bottom left of the chart; the licence's attribution notice + link are on the About page
  const logo = page.locator('.chart a[href*="tradingview"]').first();
  await expect(logo).toBeVisible();
  const box = (await logo.boundingBox())!, chart = (await page.locator(".chart").first().boundingBox())!;
  expect(box.x - chart.x).toBeLessThan(chart.width / 4);                      // left
  expect(box.y - chart.y).toBeGreaterThan(chart.height / 2);                  // bottom
  await expect(page.locator("footer")).not.toContainText("TradingView");
  await page.locator("footer").getByRole("button", { name: "About" }).click();
  const about = page.locator(".modal.about");
  await expect(about).toContainText("TradingView Lightweight Charts™, Copyright © 2023 TradingView, Inc.");
  await expect(about.locator('a[href="https://www.tradingview.com/"]')).toBeVisible();
  await about.getByRole("button", { name: "Close" }).click();
  await expect(about).toHaveCount(0);
});

test("live ticks move the quote", async ({ page }) => {
  await openApp(page);
  const first = await page.locator(".quote b").textContent();
  await expect.poll(() => page.locator(".quote b").textContent(), { timeout: 20_000 }).not.toBe(first);
});

test("symbol search with exchange filter switches the chart", async ({ page }) => {
  await openApp(page);
  await page.locator(".search input").click();
  await expect(page.locator(".search-ex button").first()).toContainText("All");
  await page.locator(".search input").fill("TCS");
  const row = page.locator(".dropdown li", { hasText: "TCS" }).first();
  await expect(row).toBeVisible();
  await row.click();
  await expect(page.locator(".legend-row").first()).toContainText("NSE:TCS");
  await page.reload();                                       // the open symbol is remembered
  await expect(page.locator(".legend-row").first()).toContainText("NSE:TCS");
});

test("timeframe dropdown lists every timeframe and remembers the choice", async ({ page }) => {
  await openApp(page);
  const btn = page.locator(".tf-btn");
  await expect(btn).toContainText("D");
  await btn.click();
  const items = page.locator(".tf-menu .menu-item");
  await expect(items).toHaveCount(12);
  for (const name of ["1 minute", "Hourly", "Daily", "Weekly", "Monthly", "Yearly"]) {
    await expect(items.filter({ hasText: name })).toHaveCount(1);
  }
  await items.filter({ hasText: "Weekly" }).click();
  await expect(btn).toContainText("W");
  await expect(page.locator(".legend-row").first()).toContainText("· 1W");
  await page.reload();
  await expect(page.locator(".tf-btn")).toContainText("W");
});

test("range presets pick a fitting timeframe and highlight", async ({ page }) => {
  await openApp(page);
  const range = (r: string) => page.locator(".rangebar button", { hasText: new RegExp(`^${r}$`) });
  await range("5D").click();
  await expect(page.locator(".tf-btn")).toContainText("15m");
  await expect(range("5D")).toHaveClass(/active/);
  await range("1Y").click();
  await expect(page.locator(".tf-btn")).toContainText("D");
  await range("All").click();
  await expect(page.locator(".tf-btn")).toContainText("M");
  await expect(page.locator(".rangebar")).toContainText("Monthly");
  // picking a timeframe by hand clears the range highlight
  await page.locator(".tf-btn").click();
  await page.locator(".tf-menu .menu-item", { hasText: "Daily" }).click();
  await expect(page.locator(".rangebar button.active")).toHaveCount(0);
});

test("day view by default (even with a dark OS), night toggle is remembered", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await openApp(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.locator(".theme-toggle")).toContainText("Day");
  await page.locator(".theme-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator(".theme-toggle")).toContainText("Night");
});

test("zoom in / out and move left / right from the buttons at the bottom middle of the chart", async ({ page }) => {
  await openApp(page);
  const bar = page.getByRole("toolbar", { name: "Zoom and move" });
  await expect(bar.getByRole("button")).toHaveText(["＋", "−", "◀", "▶"]);
  const box = (await bar.boundingBox())!, chart = (await page.locator(".chart-wrap").boundingBox())!;
  expect(Math.abs(box.x + box.width / 2 - (chart.x + chart.width / 2))).toBeLessThan(60);   // centred
  expect(chart.y + chart.height - (box.y + box.height)).toBeLessThan(80);                   // at the bottom

  const range = async () => ({ from: Number(await bar.getAttribute("data-from")), to: Number(await bar.getAttribute("data-to")) });
  await expect(bar).toHaveAttribute("data-from", /\d/);
  const r0 = await range();
  const w0 = r0.to - r0.from;
  await bar.getByRole("button", { name: "Zoom in" }).click();
  await expect.poll(async () => { const r = await range(); return r.to - r.from; }).toBeLessThan(w0 * 0.8);
  const r1 = await range();
  expect(r1.to).toBeCloseTo(r0.to, 0);                                                     // right edge kept
  await bar.getByRole("button", { name: "Zoom out" }).click();
  await bar.getByRole("button", { name: "Zoom out" }).click();
  await expect.poll(async () => { const r = await range(); return r.to - r.from; }).toBeGreaterThan(r1.to - r1.from);
  const r2 = await range();
  await bar.getByRole("button", { name: "Move left" }).click();
  await expect.poll(async () => (await range()).from).toBeLessThan(r2.from - 1);           // earlier bars
  const r3 = await range();
  expect(r3.to - r3.from).toBeCloseTo(r2.to - r2.from, 0);                                 // same width
  await bar.getByRole("button", { name: "Move right" }).click();
  await expect.poll(async () => (await range()).from).toBeGreaterThan(r3.from + 1);        // later bars

  // moving right stops at the latest bar (plus a small gap); the button is then disabled
  const right = bar.getByRole("button", { name: "Move right" });
  for (let k = 0; k < 20 && (await right.isEnabled()); k++) await right.click();
  await expect(right).toBeDisabled();
  const atEnd = await range();
  await right.click({ force: true });                                                      // no effect when disabled
  expect((await range()).to).toBeCloseTo(atEnd.to, 1);

  // moving left stops at the first bar (older history loads as it is reached), never before it
  await page.locator(".rangebar button", { hasText: "All" }).click();
  await bar.getByRole("button", { name: "Zoom in" }).click();
  const left = bar.getByRole("button", { name: "Move left" });
  for (let k = 0; k < 60 && (await left.isEnabled()); k++) { await left.click(); await page.waitForTimeout(60); }
  await expect(left).toBeDisabled();
  expect((await range()).from).toBeGreaterThanOrEqual(-0.01);
  await expect(right).toBeEnabled();
});
