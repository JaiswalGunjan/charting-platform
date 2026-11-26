import type { Page } from "@playwright/test";
import { expect, openApp, resetBackend, test } from "./fixtures";

test.beforeEach(async ({ request }) => resetBackend(request));

/** The Setup Screener page (/?page=setups); a signal clicked there opens its chart in one shared Charting Lab tab. */
async function openSetups(page: Page) {
  await openApp(page, { symbol: "NSE:RELIANCE", tf: "1W", patterns: [] });
  await page.goto("/?page=setups");
  const panel = page.locator(".panel.scanner.page");
  let chart: Page | null = null;
  /** Click a row's symbol link; return the chart tab (opened by the first click, reused by the next ones). */
  const openRow = async (row: ReturnType<Page["locator"]>) => {
    const link = row.locator("a.scan-sym");
    if (!chart) [chart] = await Promise.all([page.context().waitForEvent("page"), link.click()]);
    else await link.click();
    return chart!;
  };
  return { panel, openRow };
}

test("setup screener: breakouts with entry / SL / qty, near misses, setup filter, why this breakout", async ({ page }) => {
  const { panel, openRow } = await openSetups(page);
  await expect(panel).toContainText("scanner offline");                   // the test scanner is not running
  await expect(panel.getByRole("group", { name: "Scan market" }).locator("button.active")).toHaveText("NSE");
  await expect(panel.getByLabel("Scan date")).toHaveValue("2026-11-23");            // newest NSE scan first
  await expect(panel).toContainText("market weak bear");
  // a saved scan is not run again: the run button shows it as done
  await expect(panel.locator(".scan-pick .run-btn")).toHaveText("✓ Scanned");
  await expect(panel.locator(".scan-pick .run-btn")).toBeDisabled();

  // breakouts (default): the plan of each breakout
  await expect(panel.locator(".scan-views button.active")).toContainText("Breakouts");
  await expect(panel.locator(".scan-table thead")).toContainText("Entry");
  await expect(panel.locator(".scan-table thead")).toContainText("SL");
  const sig = panel.locator(".scan-table tbody tr:not(.why-row)", { hasText: "TCS" });
  await expect(sig).toContainText("breakout");
  await expect(sig).toContainText("2,400.00");                             // entry = signal-day close
  await expect(sig).toContainText("2,328.00");                             // stop loss
  await expect(sig).toContainText("-3.0%");
  await expect(sig).toContainText("69");          // quantity at Rs 10 L: floor(10,00,000 x 1% x 0.5 / 72)
  await expect(sig).toContainText("₹1,65,600 · 16.6%");                    // the position as a full rupee amount
  // score column, sorted by score, highest first (not by the scanner's rank)
  await expect(panel.locator(".scan-table thead")).toContainText("Score");
  await expect(panel.locator(".scan-table tbody tr .scan-score")).toHaveText(["9.95", "9.80"]);
  await expect(panel.locator(".scan-table tbody tr:not(.why-row)").first()).toContainText("WIPRO");
  await expect(panel.locator(".scan-views button")).toHaveText([/Breakouts/, /Near misses/]);
  await expect(panel.getByRole("link", { name: "full report ↗" }))             // the report in our theme
    .toHaveAttribute("href", /^\/api\/scanner\/report\/NSE_daily_\d{4}-\d{2}-\d{2}\/index\.html$/);

  // the symbol is a link to its chart (daily, Entry / SL, the setup's pattern on); it does not open the summary
  await expect(sig.locator("a.scan-sym")).toHaveAttribute("href", "/?scan=NSE_daily_2026-11-23&symbol=TCS&setup=BBR");
  const chart = await openRow(sig);
  await expect(panel.locator(".why")).toHaveCount(0);
  await expect(chart.locator(".legend-row").first()).toContainText("NSE:TCS");
  await expect(chart.locator(".tf-btn")).toContainText("D");
  await expect(chart.locator(".scanner-hit"))
    .toContainText("Bad break recovery 2026-11-23 · breakout · entry 2,400.00 · SL 2,328.00 (-3.0%) · qty 69");
  await expect(chart.getByRole("button", { name: /◈ Patterns/ })).toContainText("1"); // BBR switched on

  // a row click opens the trade summary right under the row; a second click closes it
  await sig.click();
  await expect(sig).toHaveClass(/open/);
  const why = panel.locator(".why");
  await expect(why).toContainText("Why this breakout: TCS · BBR · 2026-11-23");
  await expect(panel.locator(".scan-table tbody tr.why-row")).toHaveCount(1);
  const below = await panel.locator(".scan-table tbody tr").evaluateAll((trs) =>
    trs.findIndex((t) => t.classList.contains("why-row")) - trs.findIndex((t) => t.classList.contains("open")));
  expect(below).toBe(1);                                                    // directly south of its row
  await sig.click();
  await expect(panel.locator(".why")).toHaveCount(0);
  await expect(sig).not.toHaveClass(/open/);
  await sig.click();
  await expect(why).toContainText("Why this breakout: TCS · BBR · 2026-11-23");
  for (const title of ["What the pattern is: Bad break recovery", "Why today is the entry", "Where the stop is and why",
                       "How the position exits", "Position size", "Warnings and context"]) {
    await expect(why).toContainText(title);
  }
  await expect(why).toContainText("Stop ₹2,328.00 = 3.00% below the entry ₹2,400.00");
  await expect(why).toContainText("1R = ₹72.00");
  await expect(why).toContainText("+2R = ₹2,544.00");
  await expect(why).toContainText("Portfolio size ₹1,000,000.00");

  // the portfolio box (full rupees) re-sizes the table and the explanation
  const eq = panel.getByLabel("Portfolio size in rupees");
  await expect(eq).toHaveValue("1000000");
  await eq.fill("2000000");
  await expect(sig).toContainText("138");
  await expect(why).toContainText("Portfolio size ₹2,000,000.00");
  await expect(why).toContainText("Shares = risk / (entry - stop) = 138");
  await eq.fill("250000");
  await expect(sig).toContainText("17");                                    // floor(2,50,000 x 1% x 0.5 / 72)
  await eq.fill("");                                                        // empty: no sizes, no error
  await expect(sig.locator("td").last()).toHaveText("—");
  await eq.fill("2000000");
  await page.reload();                                                      // remembered
  await expect(panel.getByLabel("Portfolio size in rupees")).toHaveValue("2000000");
  await openRow(panel.locator(".scan-table tbody tr:not(.why-row)", { hasText: "TCS" }));  // the chart sizes with it too
  await expect(chart.locator(".scanner-hit")).toContainText("qty 138");
  await panel.getByRole("button", { name: "reset" }).click();
  await expect(panel.getByLabel("Portfolio size in rupees")).toHaveValue("1000000");

  // risk per trade: default 1%; 2% doubles the quantity, and the explanation follows
  const risk = panel.getByLabel("Risk per trade in percent");
  await expect(risk).toHaveValue("1");
  await expect(panel.locator(".field.equity")).toContainText("At risk per trade ₹5,000 = 1% x market multiplier 0.5");
  await risk.fill("2");
  await expect(sig).toContainText("138");
  await expect(panel.locator(".field.equity")).toContainText("At risk per trade ₹10,000 = 2%");
  await panel.locator(".scan-table tbody tr:not(.why-row)", { hasText: "TCS" }).click();
  await expect(why).toContainText("risk 2% per trade");
  await page.reload();
  await expect(panel.getByLabel("Risk per trade in percent")).toHaveValue("2");
  await panel.getByRole("button", { name: "reset" }).click();
  await expect(panel.getByLabel("Risk per trade in percent")).toHaveValue("1");
  await expect(sig).toContainText("69");

  // company names under the symbols, and a search over symbol and company name
  const tcsName = (await (await page.request.get("/api/symbols?q=TCS")).json())
    .find((x: { symbol: string }) => x.symbol === "NSE:TCS").name as string;
  await expect(sig.locator(".scan-name")).toHaveText(tcsName);
  const search = panel.getByLabel("Search symbol or company");
  await search.fill(tcsName.slice(0, 5).toLowerCase());
  await expect(panel.locator(".scan-table tbody tr:not(.why-row)")).toHaveCount(1);
  await expect(panel.locator(".scan-table tbody tr:not(.why-row)")).toContainText("TCS");
  await search.fill("wip");
  await expect(panel.locator(".scan-table tbody tr:not(.why-row)")).toContainText("WIPRO");
  await search.fill("no-such-stock");
  await expect(panel.locator(".scan-table tbody")).toContainText('No breakout matches "no-such-stock"');
  await search.fill("");

  // no setup list (setups are explained in "Why this trade" and in the Pattern Screener): a filter row instead
  await expect(panel).not.toContainText("setups in this scan");
  // the market note (a half-size day here) and, at the bottom, what the score is made of
  await expect(panel.locator(".market-note")).toContainText("Market rule: positions at x0.5 size");
  await expect(panel.locator(".score-note")).toContainText("What we consider to calculate score");
  await expect(panel.locator(".score-note li").first()).toHaveText("Cycle phase");   // attribute names only
  await expect(panel.locator(".score-note")).toContainText("Soft misses (lower the score)");
  expect(await panel.locator(".score-note").innerText()).not.toMatch(/\d\.\d|priority|\.py| x \d/);
  // no buy / sell words anywhere on the page (SEBI)
  expect(await panel.innerText()).not.toMatch(/\b(buy|buys|buying|bought|sell|sells|selling|sold)\b/i);
  const chips = panel.getByRole("group", { name: "Filter by setup" }).getByRole("button");
  await expect(chips).toHaveText([/All\s*2/, /PP\s*2/, /BBR\s*1/]);     // PP: WIPRO's own, and with TCS
  await expect(chips.filter({ hasText: "BBR" })).toHaveAttribute("title", /Bad break recovery/);
  const tableRows = panel.locator(".scan-table tbody tr:not(.why-row)");
  const pp = chips.filter({ hasText: "PP" }), bbr = chips.filter({ hasText: "BBR" }), all = chips.filter({ hasText: "All" });
  // TCS is a BBR breakout with PP on the same day; WIPRO is a PP breakout. Its other setups show as "+PP"
  await expect(panel.locator(".scan-table tbody tr", { hasText: "TCS" }).locator(".tag.also")).toHaveText("+PP");
  await pp.click();                                                         // PP: its own or on the same day
  await expect(tableRows).toHaveCount(2);
  await expect(pp).toHaveAttribute("aria-pressed", "true");
  await expect(chips).toHaveText([/All\s*2/, /PP\s*2/, /BBR\s*1/]);         // ticking BBR as well would leave 1
  await bbr.click();                                                        // AND: stocks with both PP and BBR
  await expect(tableRows).toHaveCount(1);
  await expect(tableRows).toContainText("TCS");
  await expect(pp).toHaveClass(/on/);
  await expect(bbr).toHaveClass(/on/);
  await expect(all).not.toHaveClass(/on/);
  await expect(panel.locator(".setup-filter")).toContainText("1 of 2 with all of PP + BBR");
  await pp.click();                                                         // untick PP: BBR alone
  await expect(tableRows).toHaveCount(1);
  await expect(tableRows).toContainText("TCS");
  await all.click();                                                        // All clears the selection
  await expect(tableRows).toHaveCount(2);
  await expect(all).toHaveClass(/on/);
  await expect(bbr).not.toHaveClass(/on/);

  // near misses show why they failed; opening one shows it on the chart as a near miss
  await panel.locator(".scan-views button", { hasText: "Near misses" }).click();
  await expect(chips).toHaveText([/All\s*1/, /VCP\s*1/]);
  const near = panel.locator(".scan-table tbody tr:not(.why-row)", { hasText: "INFY" });
  await expect(near).toContainText("no ATR contraction");               // the reason, without its rule code
  await expect(near).not.toContainText("S8-R003");
  await openRow(near);
  await near.click();
  await expect(chart.locator(".legend-row").first()).toContainText("NSE:INFY");
  await expect(chart.locator(".scanner-hit")).toContainText("near miss: no ATR contraction");
  await expect(why).toContainText("Why it is not a breakout today");
  await expect(why).toContainText("failed: no ATR contraction");
  expect(await panel.innerText()).not.toMatch(/\b(S\d+[A-Z]?|SD)-R\d/);       // no rulebook codes anywhere
  await why.getByTitle("Close").click();
  await expect(panel.locator(".why")).toHaveCount(0);

  // the overlay belongs to the signal's symbol only
  await chart.locator(".search input").fill("RELIANCE");
  await chart.locator(".dropdown li", { hasText: "RELIANCE" }).first().click();
  await expect(chart.locator(".scanner-hit")).toHaveCount(0);
});

test("the chart page has no alerts or scanner tab; a report chart link still opens the signal", async ({ page }) => {
  await openApp(page);
  await expect(page.getByRole("button", { name: /Alert/ })).toHaveCount(0);         // no Alert button
  await expect(page.locator(".sidebar .tabs")).toHaveCount(0);                      // no tabs: the watchlist only
  await expect(page.locator(".sidebar")).not.toContainText("Alerts");
  await expect(page.locator(".sidebar .panel.scanner")).toHaveCount(0);
  await expect(page.locator(".wl tbody tr").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /Explain/ })).toHaveCount(0);
  await page.keyboard.press("Alt+a");                                             // the old shortcut does nothing
  await expect(page.locator(".modal.alert-dialog")).toHaveCount(0);

  // the scanner report's chart link opens the chart with the signal, sized with the saved portfolio
  await page.goto("/api/scanner/report/NSE_daily_2026-11-23/charts/TCS_BBR.html");
  await expect(page).toHaveURL(/\/$/);                                              // the address is cleaned up
  await expect(page.locator(".legend-row").first()).toContainText("NSE:TCS");
  await expect(page.locator(".scanner-hit")).toContainText("Bad break recovery 2026-11-23 · breakout");
  await expect(page.locator(".scanner-hit")).toContainText("qty 69");
});

test("setup screener: a date picker, then a market; NYSE and NASDAQ scans open; run only what is not saved", async ({ page }) => {
  const { panel, openRow } = await openSetups(page);
  await expect(panel.locator(".panel-head").first()).toContainText("Setup Scanner");
  await expect(panel.locator(".scan-pick .step")).toHaveText([/1\s*Date/, /2\s*Market/]);
  const runBtn = panel.locator(".scan-pick .run-btn");
  await expect(runBtn).toHaveText("✓ Scanned");                                       // 23 Nov is saved
  await expect(runBtn).toBeDisabled();
  await expect(panel.getByText("New scan")).toHaveCount(0);
  const markets = panel.getByRole("group", { name: "Scan market" });
  await expect(markets.getByRole("button")).toHaveText(["NSE", "NYSE", "NASDAQ"]);
  const market = (m: string) => markets.getByRole("button", { name: m, exact: true }).click();
  const date = panel.getByLabel("Scan date");
  await expect(date).toHaveValue("2026-11-23");
  await expect(date).toHaveAttribute("min", "2026-11-20");                             // the saved range
  await expect(date).toHaveAttribute("max", "2026-11-23");

  // an older NSE session; a weekend shows the Friday scan; a day without a scan says so
  await date.fill("2026-11-20");
  await expect(panel.locator(".scan-table tbody tr:not(.why-row)").first()).toContainText("HDFCBANK");
  await date.fill("2026-11-22");
  await expect(panel).toContainText("was not a session: showing the scan of 20 Nov 2026");
  await expect(panel.locator(".scan-table tbody tr:not(.why-row)").first()).toContainText("HDFCBANK");
  await date.fill("2026-11-10");
  await expect(panel.locator(".scan-missing")).toContainText("No NSE scan is saved for 10 Nov 2026");
  await expect(runBtn).toBeDisabled();                       // the test scanner is offline and has no data for it
  await expect(panel.locator(".scan-table")).toHaveCount(0);
  await panel.getByRole("button", { name: "Latest", exact: true }).click();
  await expect(date).toHaveValue("2026-11-23");
  await expect(panel.locator(".scan-table tbody tr:not(.why-row)").first()).toContainText("WIPRO");

  // the date stays when the market changes: 20 Nov exists for every market
  await date.fill("2026-11-20");
  for (const [m, sym] of [["NYSE", "IBM"], ["NASDAQ", "AAPL"]]) {
    await market(m);
    await expect(date).toHaveValue("2026-11-20");
    const r = panel.locator(".scan-table tbody tr:not(.why-row)").first();
    await expect(r).toContainText(sym);
    const chart = await openRow(r);
    await expect(chart.locator(".legend-row").first()).toContainText(`${m}:${sym}`);
    await r.click();
    await expect(panel.locator(".why")).toContainText(`Why this breakout: ${sym}`);
    await expect(panel.locator(".why")).toContainText("$");                  // US prices in dollars
  }

  // the portfolio box follows the scan's currency: dollars for NYSE / NASDAQ, rupees for NSE, both full amounts
  await market("NYSE");
  const usd = panel.getByLabel("Portfolio size in dollars");
  await expect(usd).toHaveValue("100000");                                  // default $100,000
  await expect(panel.locator(".field.equity")).not.toContainText("lakh");
  await expect(panel.locator(".field.equity")).toContainText("At risk per trade $1,000 = 1%");
  const ibm = panel.locator(".scan-table tbody tr:not(.why-row)", { hasText: "IBM" });
  await expect(ibm).toContainText("138");                                   // floor($100,000 x 1% / 7.20)
  await expect(ibm).toContainText("$33,120 · 33.1%");
  await ibm.click();
  await expect(panel.locator(".why")).toContainText("Portfolio size $100,000.00");
  await usd.fill("50000");
  await expect(ibm).toContainText("69");
  await expect(panel.locator(".why")).toContainText("Portfolio size $50,000.00");

  await market("NSE");                                                      // rupees again, its own value
  await expect(panel.getByLabel("Portfolio size in rupees")).toHaveValue("1000000");
  await expect(panel.getByLabel("Portfolio size in dollars")).toHaveCount(0);
  await market("NASDAQ");
  await expect(panel.getByLabel("Portfolio size in dollars")).toHaveValue("50000"); // remembered per currency

  // a day the market rule blocks: a short note says which rule, and the size is still shown ("if allowed")
  const note = panel.locator(".market-note");
  await expect(note).toHaveClass(/blocked/);
  await expect(note).toContainText("Market rule: no new entries today");
  await expect(note).toContainText("Impulse (-,-) on the Russell 2000");
  await expect(note).toContainText("both ticked down");
  const aapl = panel.locator(".scan-table tbody tr:not(.why-row)", { hasText: "AAPL" });
  await expect(aapl.locator(".qty-blocked")).toHaveText("if allowed");
  await expect(aapl.locator("td").last()).toContainText("72");          // floor($50,000 x 1% x 1 / 6.90) = 72
  await expect(panel.locator(".field.equity")).toContainText("sizes are shown at the full multiplier");
  await market("NYSE");                                                    // a normal day: no note, no marker
  await expect(panel.locator(".market-note")).toHaveCount(0);
  await expect(panel.locator(".qty-blocked")).toHaveCount(0);
});

test("Setup Screener opens in the same tab, next to the Pattern Screener; a signal opens its chart", async ({ page }) => {
  await openApp(page);
  const links = page.locator(".topbar a.toolbar-link");
  await expect(links).toHaveText(["▦ Pattern Screener", "▤ Setup Screener"]);       // side by side
  await expect(links.first()).not.toHaveAttribute("target", /.+/);                 // same tab
  const pagesBefore = page.context().pages().length;
  await page.getByRole("link", { name: "▤ Setup Screener" }).click();
  const setups = page;                                                             // the same tab, not a new one
  expect(page.context().pages().length).toBe(pagesBefore);
  await expect(setups).toHaveURL(/\?page=setups$/);
  await expect(setups).toHaveTitle("Setup Screener · Charting Lab");
  await expect(setups.locator(".page-title")).toHaveText("Setup Screener");
  const panel = setups.locator(".panel.scanner.page");
  await expect(panel.getByRole("group", { name: "Scan market" }).locator("button.active")).toHaveText("NSE");
  await expect(panel.getByLabel("Portfolio size in rupees")).toHaveValue("1000000");
  // "Risk per trade" sits to the right of "Portfolio size", on the same line
  const pf = (await panel.getByLabel("Portfolio size in rupees").boundingBox())!;
  const rk = (await panel.getByLabel("Risk per trade in percent").boundingBox())!;
  expect(rk.x).toBeGreaterThan(pf.x + pf.width);
  expect(Math.abs(rk.y - pf.y)).toBeLessThan(6);

  // a signal shows its explanation here and opens its chart in a Charting Lab tab
  const tcs = panel.locator(".scan-table tbody tr:not(.why-row)", { hasText: "TCS" });
  const [chart] = await Promise.all([setups.context().waitForEvent("page"), tcs.locator("a.scan-sym").click()]);
  await tcs.click();
  await expect(panel.locator(".why")).toContainText("Why this breakout: TCS · BBR · 2026-11-23");
  await expect(chart.locator(".legend-row").first()).toContainText("NSE:TCS");
  await expect(chart.locator(".scanner-hit")).toContainText("Bad break recovery 2026-11-23");

  // changing the portfolio re-sizes here without opening another chart tab
  const before = setups.context().pages().length;
  await panel.getByLabel("Portfolio size in rupees").fill("2000000");
  await expect(panel.locator(".scan-table tbody tr:not(.why-row)", { hasText: "TCS" })).toContainText("138");
  await setups.waitForTimeout(600);
  expect(setups.context().pages().length).toBe(before);
});
