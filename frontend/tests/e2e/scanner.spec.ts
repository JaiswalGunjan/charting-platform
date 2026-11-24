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
  await expect(sig).toContainText("69");          // quantity at Rs 10 L: floor(10,00,000 x 1% x 0.5 / 72)
  await expect(panel.locator(".scan-views button")).toHaveText([/Buy setups/, /Near misses/]);   // no "All signals"

  await sig.click();
  await expect(sig).toHaveClass(/sel/);
  await expect(page.locator(".legend-row").first()).toContainText("NSE:TCS");
  await expect(page.locator(".tf-btn")).toContainText("D");                // scanner signals are daily
  await expect(page.locator(".scanner-hit"))
    .toContainText("Bad break recovery 2026-11-23 · would buy · entry 2,400.00 · SL 2,328.00 (-3.0%) · qty 69");
  await expect(page.getByRole("button", { name: /◈ Patterns/ })).toContainText("1"); // BBR pattern switched on

  // "why this trade": the six-part brief with the trade plan
  const why = panel.locator(".why");
  await expect(why).toContainText("Why this trade: TCS · BBR · 2026-11-23");
  for (const title of ["What the pattern is: Bad break recovery", "Why today is the entry", "Where the stop is and why",
                       "How we would sell", "Position size", "Warnings and context"]) {
    await expect(why).toContainText(title);
  }
  await expect(why).toContainText("Stop ₹2,328.00 = 3.00% below the entry ₹2,400.00");
  await expect(why).toContainText("1R = ₹72.00");
  await expect(why).toContainText("+2R = ₹2,544.00");
  await expect(why).toContainText("Equity ₹1,000,000.00");

  // a new equity re-sizes the table, the chart legend and the explanation
  const eq = panel.getByLabel("Equity in lakh");
  await expect(eq).toHaveValue("10");                                       // the box is in lakh: 10 = Rs 10,00,000
  await expect(panel.locator(".field.equity")).not.toContainText("Your equity");          // no label text
  await expect(panel.locator(".field.equity")).not.toContainText("= ₹");                 // no rupee echo
  await eq.fill("20");
  await expect(sig).toContainText("138");
  await expect(page.locator(".scanner-hit")).toContainText("qty 138");
  await expect(why).toContainText("Equity ₹2,000,000.00");
  await expect(why).toContainText("Shares = risk / (entry - stop) = 138");
  await eq.fill("2.5");                                                     // fractions of a lakh work
  await expect(sig).toContainText("17");                                    // floor(2,50,000 x 1% x 0.5 / 72)
  await eq.fill("");                                                        // empty: no sizes, no error
  await expect(sig.locator("td").last()).toHaveText("—");                    // no size without an equity
  await eq.fill("20");
  await page.reload();                                                      // remembered (in rupees internally)
  await page.locator(".tabs button", { hasText: "Scanner" }).click();
  await expect(panel.getByLabel("Equity in lakh")).toHaveValue("20");
  await panel.getByRole("button", { name: "reset" }).click();
  await expect(panel.getByLabel("Equity in lakh")).toHaveValue("10");
  await panel.locator(".scan-table tbody tr", { hasText: "TCS" }).click();

  // the setup guide explains each setup in the scan
  const guide = panel.locator(".setup-guide");
  await expect(guide).toContainText("Bad break recovery");
  await expect(guide).toContainText("Volatility contraction pattern");
  await guide.locator(".setup-name", { hasText: "BBR" }).click();
  await expect(guide.locator(".setup-text")).toBeVisible();
  // labelled counts; clicking one opens that list filtered to the setup
  const bbr = guide.locator(".setup-item", { hasText: "Bad break recovery" });
  await expect(bbr.locator(".setup-counts")).toContainText("1 buy signal · 0 near misses (formed, failed a hard rule)");
  const vcp = guide.locator(".setup-item", { hasText: "Volatility contraction pattern" });
  await vcp.getByRole("button", { name: "1 near miss" }).click();
  await expect(panel.locator(".scan-views button.active")).toContainText("Near misses");
  await expect(panel.locator(".setup-filter")).toContainText("VCP Volatility contraction pattern only");
  await expect(panel.locator(".scan-table tbody tr")).toHaveCount(1);
  await expect(panel.locator(".scan-table tbody tr")).toContainText("INFY");
  await panel.locator(".setup-filter").getByRole("button", { name: /show all setups/ }).click();
  await expect(panel.locator(".setup-filter")).toHaveCount(0);

  // near misses show why they failed; opening one switches its pattern on too
  await panel.locator(".scan-views button", { hasText: "Near misses" }).click();
  const near = panel.locator(".scan-table tbody tr", { hasText: "INFY" });
  await expect(near).toContainText("S8-R003");
  await near.click();
  await expect(page.locator(".legend-row").first()).toContainText("NSE:INFY");
  await expect(page.locator(".scanner-hit")).toContainText("near miss: S8-R003");
  await expect(panel.locator(".why")).toContainText("Why it is not a buy today");
  await expect(panel.locator(".why")).toContainText("failed: S8-R003");
  await panel.locator(".why").getByTitle("Close").click();
  await expect(panel.locator(".why")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /◈ Patterns/ })).toContainText("2");

  // the overlay belongs to the signal's symbol only
  await page.locator(".search input").fill("RELIANCE");
  await page.locator(".dropdown li", { hasText: "RELIANCE" }).first().click();
  await expect(page.locator(".scanner-hit")).toHaveCount(0);
});
