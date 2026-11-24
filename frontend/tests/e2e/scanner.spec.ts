import { expect, openApp, resetBackend, test } from "./fixtures";

test.beforeEach(async ({ request }) => resetBackend(request));

test("scanner tab: past scans, buy setups with entry / SL / qty, near misses, setup guide", async ({ page }) => {
  await openApp(page, { symbol: "NSE:RELIANCE", tf: "1W", patterns: [] });
  await page.locator(".tabs button", { hasText: "Scanner" }).click();
  const panel = page.locator(".panel.scanner");
  await expect(panel).toContainText("scanner offline");                   // the test scanner is not running
  await expect(panel.locator(".field", { hasText: "Past scans (history)" }).locator("select"))
    .toContainText("23 Nov 2026 · NSE · 1 signal");
  await expect(panel).toContainText("market weak bear");
  await expect(panel.getByRole("button", { name: "Run scan" })).toHaveCount(0); // only while the scanner runs

  // buy setups view (default): the trade plan of each buy
  await expect(panel.locator(".scan-views button.active")).toContainText("Buy setups");
  await expect(panel.locator(".scan-table thead")).toContainText("Entry");
  await expect(panel.locator(".scan-table thead")).toContainText("SL");
  const sig = panel.locator(".scan-table tbody tr", { hasText: "TCS" });
  await expect(sig).toContainText("would buy");
  await expect(sig).toContainText("2,400.00");                             // entry = signal-day close
  await expect(sig).toContainText("2,328.00");                             // stop loss
  await expect(sig).toContainText("-3.0%");
  await expect(sig).toContainText("10");                                   // quantity

  await sig.click();
  await expect(sig).toHaveClass(/sel/);
  await expect(page.locator(".legend-row").first()).toContainText("NSE:TCS");
  await expect(page.locator(".tf-btn")).toContainText("D");                // scanner signals are daily
  await expect(page.locator(".scanner-hit"))
    .toContainText("Bad break recovery 2026-11-23 · would buy · entry 2,400.00 · SL 2,328.00 (-3.0%) · qty 10");
  await expect(page.getByRole("button", { name: /Patterns/ })).toContainText("1"); // BBR pattern switched on

  // the setup guide explains each setup in the scan
  const guide = panel.locator(".setup-guide");
  await expect(guide).toContainText("Bad break recovery");
  await expect(guide).toContainText("Volatility contraction pattern");
  await guide.locator(".setup-title", { hasText: "BBR" }).click();
  await expect(guide.locator(".setup-text")).toBeVisible();

  // near misses show why they failed; opening one switches its pattern on too
  await panel.locator(".scan-views button", { hasText: "Near misses" }).click();
  const near = panel.locator(".scan-table tbody tr", { hasText: "INFY" });
  await expect(near).toContainText("S8-R003");
  await near.click();
  await expect(page.locator(".legend-row").first()).toContainText("NSE:INFY");
  await expect(page.locator(".scanner-hit")).toContainText("near miss: S8-R003");
  await expect(page.getByRole("button", { name: /Patterns/ })).toContainText("2");

  // the overlay belongs to the signal's symbol only
  await page.locator(".search input").fill("RELIANCE");
  await page.locator(".dropdown li", { hasText: "RELIANCE" }).first().click();
  await expect(page.locator(".scanner-hit")).toHaveCount(0);
});
