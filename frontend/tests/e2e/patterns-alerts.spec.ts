import { API, expect, openApp, resetBackend, test } from "./fixtures";

test.beforeEach(async ({ request }) => resetBackend(request));

test("pattern menu shows counts for every pattern and toggles markers", async ({ page }) => {
  await openApp(page, { patterns: [] });
  await page.getByRole("button", { name: /◈ Patterns/ }).click();
  const items = page.locator(".pattern-item");
  await expect(items).toHaveCount(19);
  // every pattern gets a number, ticked or not
  await expect.poll(async () => (await items.locator(".pattern-count").allTextContents()).every((t) => /^\d+$/.test(t)))
    .toBe(true);
  const ppItem = items.filter({ hasText: "Pocket pivot" });
  const ppCount = Number(await ppItem.locator(".pattern-count").textContent());

  // ticking a pattern scans for it; the scan finds exactly as many hits as the menu said
  const scan = page.waitForResponse((r) => r.url().includes("/patterns/scan") && r.url().includes("ids=pp"));
  await ppItem.locator("input").check();
  const body = await (await scan).json();
  expect(body.markers.filter((m: { pattern: string }) => m.pattern === "pp")).toHaveLength(ppCount);
  await expect(page.getByRole("button", { name: /◈ Patterns/ })).toContainText("1");

  // group checkbox, None and Defaults
  await page.locator(".pattern-group", { hasText: "Bases" }).locator("input").check();
  await expect(items.filter({ hasText: "VCP" }).locator("input")).toBeChecked();
  await page.getByRole("button", { name: "None" }).click();
  await expect(page.locator(".pattern-item input:checked")).toHaveCount(0);
  await page.getByRole("button", { name: "Defaults" }).click();
  await expect(page.locator(".pattern-item input:checked")).toHaveCount(6);
  await page.reload();                                        // the selection is remembered
  await expect(page.getByRole("button", { name: /◈ Patterns/ })).toContainText("6");
});

test("pattern menu search filters by name, marker text and group", async ({ page }) => {
  await openApp(page, { patterns: [] });
  await page.getByRole("button", { name: /◈ Patterns/ }).click();
  const search = page.locator(".pattern-search");
  await expect(search).toBeFocused();
  const items = page.locator(".pattern-item");
  await search.fill("cup");
  await expect(items).toHaveCount(1);
  await expect(items.first()).toContainText("Cup with handle");
  await search.press("Enter");                                    // a single match: Enter ticks it
  await expect(items.first().locator("input")).toBeChecked();
  await search.fill("vcp");
  await expect(items).toHaveCount(1);
  await search.fill("shapers");                                   // group name
  await expect(items).toHaveCount(5);
  await search.fill("zzz");
  await expect(items).toHaveCount(0);
  await expect(page.locator(".pattern-menu")).toContainText("No pattern matches");
  await search.fill("");
  await expect(items).toHaveCount(19);
  await expect(page.getByRole("button", { name: /◈ Patterns/ })).toContainText("1");
});

test("create an alert from the top bar (Alt+A)", async ({ page, request }) => {
  await openApp(page);
  await page.keyboard.press("Alt+a");
  const dlg = page.locator(".modal.alert-dialog");
  await expect(dlg).toContainText("Create alert on NSE:RELIANCE");
  const price = dlg.locator("input[type=number]");
  const before = Number(await price.inputValue());
  await dlg.getByRole("button", { name: "+2%" }).click();
  await expect.poll(async () => Number(await price.inputValue())).toBeCloseTo(before * 1.02, 1);
  await dlg.getByRole("button", { name: "Create" }).click();
  await expect(page.locator(".toast")).toContainText("Alert set");
  await expect(page.locator(".tabs button", { hasText: "Alerts" })).toContainText("(1)");
  const alerts = await (await request.get(`${API}/alerts`)).json();
  expect(alerts).toHaveLength(1);
  expect(alerts[0].condition.op).toBe("crosses_above");

  // the Alert button opens the same dialog; an invalid price is refused
  await page.getByRole("button", { name: /Alert$/ }).click();
  await dlg.locator("input[type=number]").fill("0");
  await dlg.getByRole("button", { name: "Create" }).click();
  await expect(dlg.locator(".error")).toBeVisible();
});
