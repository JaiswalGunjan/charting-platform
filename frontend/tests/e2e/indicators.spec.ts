import { API, expect, openApp, resetBackend, test } from "./fixtures";

test.beforeEach(async ({ request }) => resetBackend(request));

test("add, configure, hide and remove an indicator", async ({ page }) => {
  await openApp(page);
  await page.getByRole("button", { name: /Indicators/ }).click();
  const search = page.locator(".picker-head input");
  await expect(page.locator(".picker-cats button").first()).toContainText("50");   // all 50 built-ins listed
  await search.fill("relative strength");
  await expect(page.locator(".picker-row")).toHaveCount(1);
  await search.press("Enter");                                                    // Enter adds the first match
  const chip = page.locator(".ind-chip", { hasText: "Relative Strength Index" });
  await expect(chip).toContainText("(14)");

  // settings: change the length
  await chip.locator(".chip-label").click();
  const dialog = page.locator(".modal .settings");
  await dialog.locator("label", { hasText: "Length" }).locator("input").fill("21");
  await dialog.getByRole("button", { name: "Apply" }).click();
  await expect(chip).toContainText("(21)");

  // an out-of-range input is refused: the dialog stays open and the indicator keeps its value
  await chip.locator(".chip-label").click();
  await dialog.locator("label", { hasText: "Length" }).locator("input").fill("0");
  await dialog.getByRole("button", { name: "Apply" }).click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(chip).toContainText("(21)");

  // the indicator list survives a reload
  await page.reload();
  await expect(chip).toContainText("(21)");

  await chip.getByTitle("Hide").click();
  await expect(chip).toHaveClass(/off/);
  await chip.getByTitle("Show").click();
  await expect(chip).not.toHaveClass(/off/);
  await chip.getByTitle("Remove").click();
  await expect(chip).toHaveCount(0);
});

test("style tab changes a line colour", async ({ page }) => {
  await openApp(page, { indicators: [{ key: "ema-1", id: "ema", params: { length: 20, source: "close" } }] });
  const chip = page.locator(".ind-chip", { hasText: "Exponential Moving Average" });
  await chip.locator(".chip-label").click();
  await page.locator(".tabs.inline button", { hasText: "Style" }).click();
  await page.locator(".style-row input[type=color]").first().fill("#ff0000");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(chip.locator(".swatch")).toHaveCSS("background-color", "rgb(255, 0, 0)");
});

test("custom formula indicator: errors are explained, a valid one is saved and drawn", async ({ page, request }) => {
  await openApp(page);
  await page.getByRole("button", { name: /Indicators/ }).click();
  await page.getByRole("button", { name: "+ Custom indicator" }).click();
  const editor = page.locator(".modal.editor");
  const expr = editor.locator(".plot-row input.grow").first();
  await expr.fill("ema(close, length) - sma(clse, length)");
  await editor.getByRole("button", { name: "Check" }).click();
  await expect(editor.locator(".error")).toContainText("unknown name 'clse'");
  await expect(editor.locator(".plot-row.bad")).toHaveCount(1);               // the faulty plot is marked
  await expr.fill("ema(close, length) - sma(close, length)");
  await editor.getByRole("button", { name: "Check" }).click();
  await expect(editor.locator(".ok")).toContainText("Looks good");
  await editor.getByRole("button", { name: "Save & add to chart" }).click();
  await expect(page.locator(".ind-chip", { hasText: "My indicator" })).toContainText("(20)");
  const saved = await (await request.get(`${API}/custom-indicators`)).json();
  expect(saved).toHaveLength(1);

  // delete it from the picker: the chart entry goes too
  page.on("dialog", (d) => d.accept());
  await page.getByRole("button", { name: /Indicators/ }).click();
  await page.getByRole("button", { name: /^Custom \d/ }).click();
  await page.locator(".picker-row", { hasText: "My indicator" }).getByTitle("Delete").click();
  await expect(page.locator(".picker-row", { hasText: "My indicator" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.locator(".ind-chip", { hasText: "My indicator" })).toHaveCount(0);
});
