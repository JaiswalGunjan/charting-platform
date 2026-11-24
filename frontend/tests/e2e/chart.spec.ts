import { expect, openApp, resetBackend, test } from "./fixtures";

test.beforeEach(async ({ request }) => resetBackend(request));

test("app loads: chart, quote, live badge, watchlist, attribution", async ({ page }) => {
  await openApp(page);
  await expect(page.locator(".legend-row").first()).toContainText("NSE:RELIANCE");
  await expect(page.locator(".legend-row").first()).toContainText("· 1D");
  await expect(page.locator(".chart canvas").first()).toBeVisible();
  await expect(page.locator(".quote b")).toHaveText(/[\d,]+\.\d\d/);
  await expect(page.locator(".conn")).toContainText(/Simulated ticks|Live/);
  await expect(page.locator(".wl tbody tr").first()).toBeVisible();
  // attribution: footer link kept, no TradingView logo inside the chart
  await expect(page.locator("footer a", { hasText: "TradingView Lightweight Charts" })).toBeVisible();
  await expect(page.locator('.chart a[href*="tradingview"]')).toHaveCount(0);
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
