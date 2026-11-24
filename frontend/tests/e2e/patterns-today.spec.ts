import { expect, openApp, resetBackend, test } from "./fixtures";

test.beforeEach(async ({ request }) => resetBackend(request));

test("patterns today: saved screen, AND filter with clear, category sections, sortable table, open a stock", async ({ page }) => {
  await openApp(page, { "today.minTurnover": 0, "today.patterns": [], "today.tf": "1D", "today.sort": { key: "patterns", dir: -1 } });
  await page.getByRole("button", { name: "▦ Patterns today" }).click();
  const dash = page.locator(".today");
  await expect(dash.locator("h2")).toHaveText("Patterns formed today");

  // screen once; the result is saved and shown again without re-screening
  const screenBtn = dash.getByRole("button", { name: /Screen NSE now|Update screen/ }).first();
  await screenBtn.click();
  await expect(dash.locator(".today-asof")).toContainText("Saved screen", { timeout: 30_000 });
  const savedAt = await dash.locator(".today-asof").textContent();
  await page.reload();
  await page.getByRole("button", { name: "▦ Patterns today" }).isVisible();
  await expect(dash.locator(".today-asof")).toHaveText(savedAt!);           // same saved screen, nothing re-run
  await expect(dash.getByRole("button", { name: /Update screen/ })).toBeVisible();

  // one section per category, each pattern with a description
  const sections = dash.locator(".today-section h3");
  await expect(sections).toContainText(["Volume signals", "Price cycle", "Bases", "Shapers", "Breakouts & pullbacks"]);
  await expect(dash.locator(".pcard").filter({ has: page.locator("b", { hasText: /^Pocket pivot$/ }) }))
    .toContainText("volume beats every down day");

  const count = async () => Number((await dash.locator(".today-count").textContent())!.replace(/\D/g, ""));
  const total = await count();
  expect(total).toBeGreaterThan(0);
  await expect(dash.locator(".today-selection")).toContainText("No pattern selected");
  await expect(dash.getByRole("button", { name: "Clear selection" })).toBeDisabled();

  // one pattern: only stocks with it remain
  const card = dash.locator(".pcard:not(.zero)").first();
  const label = (await card.locator(".pattern-tag").textContent())!;
  const n = Number(await card.locator(".pcard-count").textContent());
  await card.locator("input").check();
  await expect.poll(count).toBe(n);
  for (const t of await dash.locator(".today-table tbody tr .today-pats").allTextContents()) expect(t).toContain(label);

  // a second pattern: AND, so only stocks with both remain (never more than either alone)
  const second = dash.locator(".pcard:not(.on)").first();
  const both = Number(await second.locator(".pcard-count").textContent());     // count shown = stocks with both
  await second.locator("input").check();
  await expect(dash.locator(".today-selection")).toContainText("formed all of");
  await expect.poll(count).toBe(both);
  expect(both).toBeLessThanOrEqual(n);

  // clear selection resets everything
  await dash.getByRole("button", { name: "Clear selection" }).click();
  await expect.poll(count).toBe(total);
  await expect(dash.locator(".pcard.on")).toHaveCount(0);

  // sorting: by symbol ascending, then descending; by number of patterns
  const tickers = () => dash.locator(".today-table tbody tr td:first-child").allTextContents();
  await dash.locator("th", { hasText: "Symbol" }).click();
  let t = await tickers();
  expect(t).toEqual([...t].sort((a, b) => a.localeCompare(b)));
  await dash.locator("th", { hasText: "Symbol" }).click();
  t = await tickers();
  expect(t).toEqual([...t].sort((a, b) => b.localeCompare(a)));
  await dash.locator("th", { hasText: "Patterns on the latest bar" }).click();
  const npat = (await dash.locator(".today-table tbody tr .pcount").allTextContents()).map(Number);
  expect(npat).toEqual([...npat].sort((a, b) => b - a));
  await dash.locator("th", { hasText: "Close" }).click();
  const closes = (await dash.locator(".today-table tbody tr td:nth-child(3)").allTextContents()).map((x) => Number(x.replace(/,/g, "")));
  expect(closes).toEqual([...closes].sort((a, b) => b - a));

  // open a stock: chart on the same timeframe with its patterns switched on
  const first = (await tickers())[0].trim();
  await dash.locator(".today-table tbody tr").first().click();
  await expect(page.locator(".today")).toHaveCount(0);
  await expect(page.locator(".legend-row").first()).toContainText(`NSE:${first}`);
  await expect(page.locator(".tf-btn")).toContainText("D");
  await expect(page.getByRole("button", { name: /◈ Patterns/ })).not.toHaveText("◈ Patterns");
});

test("patterns today: weekly screen, turnover floor, search, saved per exchange and timeframe", async ({ page }) => {
  await openApp(page, { "today.minTurnover": 0, "today.patterns": [], "today.tf": "1W" });
  await page.getByRole("button", { name: "▦ Patterns today" }).click();
  const dash = page.locator(".today");
  await expect(dash.getByRole("button", { name: "Weekly" })).toHaveClass(/active/);

  // weekly is screened separately and labelled as the week (in progress)
  await dash.getByRole("button", { name: /Screen NSE now|Update screen/ }).first().click();
  await expect(dash.locator(".today-asof")).toContainText("week of", { timeout: 30_000 });
  await expect(dash.locator(".today-asof")).toContainText("week in progress");

  // daily keeps its own saved screen; switching back and forth does not re-screen
  await dash.getByRole("button", { name: "Daily" }).click();
  const daily = dash.getByRole("button", { name: /Screen NSE now|Update screen/ }).first();
  if ((await daily.textContent())?.includes("Screen NSE now")) {
    await daily.click();
    await expect(dash.locator(".today-asof")).toContainText("latest bar", { timeout: 30_000 });
  }
  const dailyStamp = await dash.locator(".today-asof").textContent();
  await dash.getByRole("button", { name: "Weekly" }).click();
  await expect(dash.locator(".today-asof")).toContainText("week of");
  await dash.getByRole("button", { name: "Daily" }).click();
  await expect(dash.locator(".today-asof")).toHaveText(dailyStamp!);

  const count = async () => Number((await dash.locator(".today-count").textContent())!.replace(/\D/g, ""));
  const all = await count();
  expect(all).toBeGreaterThan(0);

  // a very high turnover floor removes every stock and says why; back to 0 restores them
  const floor = dash.locator(".today-row2 label.mini input");
  await floor.fill("100000");
  await expect.poll(count).toBe(0);
  await expect(dash.locator(".today-table tbody")).toContainText("with turnover above 100000 ₹ Cr");
  await floor.fill("0");
  await expect.poll(count).toBe(all);

  // search by company name (case-insensitive) narrows the table
  const firstName = (await dash.locator(".today-table tbody tr .today-name").first().textContent())!.trim();
  await dash.getByPlaceholder("Search symbol or company").fill(firstName.slice(0, 6).toUpperCase());
  for (const n of await dash.locator(".today-table tbody tr .today-name").allTextContents()) {
    expect(n.toLowerCase()).toContain(firstName.slice(0, 6).toLowerCase());
  }
  await dash.getByPlaceholder("Search symbol or company").fill("no-such-stock");
  await expect.poll(count).toBe(0);

  // close returns to the chart
  await dash.getByRole("button", { name: "✕ Close" }).click();
  await expect(page.locator(".today")).toHaveCount(0);
  await expect(page.locator(".chart canvas").first()).toBeVisible();
});
