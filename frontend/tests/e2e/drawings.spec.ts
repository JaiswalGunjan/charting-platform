import { API, drawingCount, expect, openApp, resetBackend, SYMBOL, test } from "./fixtures";

test.beforeEach(async ({ request }) => resetBackend(request));

async function chartBox(page: import("@playwright/test").Page) {
  const box = await page.locator(".chart").boundingBox();
  if (!box) throw new Error("chart not visible");
  return box;
}

test("draw a trend line by dragging; select, recolour and delete it", async ({ page, request }) => {
  await openApp(page);
  const b = await chartBox(page);
  await page.locator(".draw-toolbar button[title^='Trend line']").click();
  await expect(page.locator(".draw-hint")).toBeVisible();
  const a = { x: b.x + b.width * 0.3, y: b.y + b.height * 0.45 };
  const z = { x: b.x + b.width * 0.6, y: b.y + b.height * 0.25 };
  await page.mouse.move(a.x, a.y);
  await page.mouse.down();
  await page.mouse.move(z.x, z.y, { steps: 8 });
  await page.mouse.up();
  await expect(page.locator(".draw-stylebar")).toBeVisible();           // the new line is selected
  await expect.poll(() => drawingCount(request)).toBe(1);

  await page.keyboard.press("Escape");                                   // deselect
  await expect(page.locator(".draw-stylebar")).toHaveCount(0);
  await page.mouse.click((a.x + z.x) / 2, (a.y + z.y) / 2);              // click on the line selects it
  await expect(page.locator(".draw-stylebar")).toBeVisible();
  await page.locator(".draw-stylebar .swatch-btn").nth(1).click();
  await expect.poll(async () => (await (await request.get(`${API}/drawings?symbol=${SYMBOL}`)).json()).items[0].color)
    .toBe("#f23645");
  await page.keyboard.press("Delete");
  await expect.poll(() => drawingCount(request)).toBe(0);
});

test("drawings survive a reload and a timeframe change", async ({ page, request }) => {
  await openApp(page);
  const b = await chartBox(page);
  await page.locator(".draw-toolbar button[title^='Trend line']").click();
  await page.mouse.move(b.x + b.width * 0.3, b.y + b.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width * 0.5, b.y + b.height * 0.3, { steps: 6 });
  await page.mouse.up();
  await expect.poll(() => drawingCount(request)).toBe(1);
  await page.reload();
  await expect(page.locator(".legend-row").first()).toContainText("NSE:RELIANCE");
  await page.locator(".tf-btn").click();
  await page.locator(".tf-menu .menu-item", { hasText: "Weekly" }).click();
  await expect(page.locator(".legend-row").first()).toContainText("· 1W");
  await page.waitForTimeout(1000);                                       // give a wrongful save time to happen
  expect(await drawingCount(request)).toBe(1);                           // loading never overwrites or drops it
});

test("one-click tools, click-click tools and Esc", async ({ page, request }) => {
  await openApp(page);
  const b = await chartBox(page);
  const at = (fx: number, fy: number) => ({ x: b.x + b.width * fx, y: b.y + b.height * fy });

  await page.locator(".draw-toolbar button[title^='Horizontal line']").click();
  const h = at(0.5, 0.4);
  await page.mouse.click(h.x, h.y);
  await expect.poll(() => drawingCount(request)).toBe(1);

  await page.locator(".draw-toolbar button[title^='Fibonacci']").click();
  const f1 = at(0.2, 0.3), f2 = at(0.35, 0.6);
  await page.mouse.click(f1.x, f1.y);
  await page.mouse.move(f2.x, f2.y, { steps: 4 });
  await page.mouse.click(f2.x, f2.y);
  await expect.poll(() => drawingCount(request)).toBe(2);

  await page.locator(".draw-toolbar button[title^='Rectangle']").click();
  await page.keyboard.press("Escape");                                   // Esc cancels the tool
  await expect(page.locator(".draw-hint")).toHaveCount(0);

  // measure is temporary and never saved
  await page.locator(".draw-toolbar button[title^='Measure']").click();
  const m1 = at(0.6, 0.6), m2 = at(0.75, 0.4);
  await page.mouse.move(m1.x, m1.y);
  await page.mouse.down();
  await page.mouse.move(m2.x, m2.y, { steps: 6 });
  await page.mouse.up();
  await page.waitForTimeout(800);
  expect(await drawingCount(request)).toBe(2);

  // remove all
  page.on("dialog", (d) => d.accept());
  await page.locator(".draw-toolbar button[title^='Remove all']").click();
  await expect.poll(() => drawingCount(request)).toBe(0);
});

test("drawings belong to their symbol", async ({ page, request }) => {
  await request.put(`${API}/drawings?symbol=NSE:TCS`, {
    data: { items: [{ id: "x", kind: "hline", pts: [{ t: 1, p: 100 }], color: "#2962ff", width: 2 }] },
  });
  await openApp(page);
  expect(await drawingCount(request, SYMBOL)).toBe(0);
  expect(await drawingCount(request, "NSE:TCS")).toBe(1);
});
