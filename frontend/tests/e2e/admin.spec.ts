import { expect, test } from "./fixtures";

// The test backend's local user is an admin; a non-admin is played by answering GET /api/auth/me in the test.
// Dashboard jobs run the nightly job's script in dry-run mode there (ADMIN_JOBS_DRY_RUN): nothing is downloaded.
const PLAIN = { id: 7, email: "asha@example.com", name: "Asha K", given_name: "Asha", picture: "", phone: "",
  is_admin: false, provider: "google", auth_mode: "google" };

test("not an admin: no dashboard, no Users page, even by their links; no admin menu", async ({ page }) => {
  await page.route("**/api/auth/me", (r) => r.fulfill({ json: PLAIN }));
  let adminCalls = 0;
  page.on("request", (r) => { if (r.url().includes("/api/admin/")) adminCalls++; });
  for (const link of ["/?page=admin", "/?page=users"]) {
    await page.goto(link);
    await expect(page.getByRole("alert")).toContainText("Not available");
    await expect(page.locator(".admin-main, .users-main")).toHaveCount(0);
  }
  expect(adminCalls).toBe(0);
  await page.goto("/?page=setups");
  await page.getByRole("button", { name: "Account" }).click();
  await expect(page.getByRole("menuitem", { name: "Admin" })).toHaveCount(0);
  await expect(page.getByRole("menuitem", { name: "Users" })).toHaveCount(0);
  await expect(page.locator(".run-btn")).toHaveCount(0);
});

test("admin dashboard: the data's state, a job started from a button, its output and history", async ({ page }) => {
  await page.goto("/?page=setups");
  await page.getByRole("button", { name: "Account" }).click();
  await page.getByRole("menuitem", { name: "Admin" }).click();
  await expect(page).toHaveURL(/\?page=admin$/);
  const nse = page.locator(".admin-data tbody tr", { hasText: "NSE" }).first();
  await expect(nse.locator("td").nth(2)).toHaveText(/^\d{4}-\d{2}-\d{2}$/);              // the last daily bar's session
  await expect(nse.locator("td").nth(4)).toHaveText("2026-11-23");                     // the test's saved setup scan
  const run = page.getByRole("group", { name: "Run a job" });
  await expect(run.getByRole("button")).toHaveText(["⭳ Download EOD data", "▤ Run setup screener",
    "▦ Run pattern screener", "⟳ Full update (download, import, setup and pattern screeners)"]);
  await run.getByLabel("Market").selectOption("NSE");
  await run.getByLabel("Session").fill("2026-11-26");
  await run.getByRole("button", { name: "▦ Run pattern screener" }).click();
  const log = page.getByLabel("Job output");
  await expect(log).toContainText("--only screen");                                     // the nightly job's step
  await expect(log).toContainText("[dry run] would run screen", { timeout: 30_000 });
  await expect(page.locator(".admin-job .job-state")).toContainText("done", { timeout: 30_000 });
  const recent = page.locator(".admin-jobs tbody tr").first();
  await expect(recent).toContainText("Run pattern screener");
  await expect(recent).toContainText("2026-11-26");
  await expect(recent).toContainText("done");
});
