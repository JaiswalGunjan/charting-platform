import type { Page, Route } from "@playwright/test";
import { expect, test } from "./fixtures";

// The test backend runs in local mode (signed in as the local user). Here GET /api/auth/me is answered by the test
// itself: signed out (401), or a signed-in user who is not an admin. Google itself is tested in backend test_m26.
const SIGNED_OUT = (r: Route) => r.fulfill({ status: 401, contentType: "application/json", body: '{"detail":"not signed in"}' });
const USER = { id: 7, email: "asha@example.com", name: "Asha K", given_name: "Asha", picture: "", phone: "",
  is_admin: false, provider: "google", auth_mode: "google" };

async function signedOut(page: Page) {
  await page.route("**/api/auth/me", SIGNED_OUT);
}

test("nothing opens before sign-in, whatever link is used; sign-in comes back to that link", async ({ page }) => {
  await signedOut(page);
  let apiCalls = 0;
  page.on("request", (r) => { if (/\/api\/(?!auth\/)/.test(r.url())) apiCalls++; });
  for (const link of ["/", "/?symbol=NSE:TCS&tf=1h", "/?page=setups", "/?page=screener",
                      "/?scan=NSE_daily_2026-11-23&symbol=TCS&setup=BBR"]) {
    await page.goto(link);
    await expect(page.getByRole("link", { name: "Sign in with Google" })).toBeVisible();
    await expect(page.locator(".chart, .panel.scanner, .today-sections")).toHaveCount(0);      // no page behind it
    const href = await page.getByRole("link", { name: "Sign in with Google" }).getAttribute("href");
    expect(href).toBe(`/api/auth/google/login?next=${encodeURIComponent(link)}`);           // back to that link
  }
  expect(apiCalls).toBe(0);                                                                   // no data was asked for
  await expect(page.locator(".signin-note")).toContainText("IP address");                     // what is recorded, said
});

test("a page that needed sign-in (?next=) is where sign-in returns; errors are shown", async ({ page }) => {
  await signedOut(page);
  await page.goto("/?next=%2Fapi%2Fscanner%2Freport%2FNSE_daily_2026-11-23%2Findex.html&signin_error=access%20denied");
  await expect(page.getByRole("alert")).toContainText("access denied");
  expect(await page.getByRole("link", { name: "Sign in with Google" }).getAttribute("href"))
    .toBe("/api/auth/google/login?next=%2Fapi%2Fscanner%2Freport%2FNSE_daily_2026-11-23%2Findex.html");
  await page.goto("/?next=https%3A%2F%2Fevil.example%2F");                                    // never another site
  expect(await page.getByRole("link", { name: "Sign in with Google" }).getAttribute("href"))
    .toBe("/api/auth/google/login?next=%2F");
});

test("a session that ends while the page is open goes to sign-in", async ({ page }) => {
  await page.route("**/api/auth/me", (r) => r.fulfill({ json: USER }));
  await page.goto("/?page=setups");
  await expect(page.locator(".panel.scanner.page")).toBeVisible();
  await page.route("**/api/scanner**", SIGNED_OUT);                                           // the session ended
  await page.unroute("**/api/auth/me");
  await signedOut(page);
  // any request now (the panel's own next one may get there first)
  await page.getByRole("button", { name: "↻" }).click({ timeout: 3000 }).catch(() => {});
  await expect(page.getByRole("link", { name: "Sign in with Google" })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("next")).toBe("/?page=setups");
});

test("signed in: the user menu; Run buttons and the Users page are for admins", async ({ page }) => {
  await page.route("**/api/auth/me", (r) => r.fulfill({ json: USER }));
  await page.goto("/?page=setups");
  await expect(page.locator(".panel.scanner.page")).toBeVisible();
  await expect(page.locator(".run-btn")).toHaveCount(0);                                      // not an admin
  await page.getByRole("button", { name: "Account" }).click();
  const menu = page.getByRole("menu");
  await expect(menu).toContainText("Asha K");
  await expect(menu).toContainText("asha@example.com");
  await expect(menu.getByRole("menuitem", { name: "Users" })).toHaveCount(0);
  await expect(menu.getByRole("menuitem", { name: "Sign out" })).toBeVisible();
  await page.goto("/?page=screener");
  await expect(page.locator(".today-steps")).toBeVisible();
  await expect(page.locator(".run-btn")).toHaveCount(0);
  // the local user (the test backend's) is an admin: Run buttons, and the Users page with its stats
  await page.unroute("**/api/auth/me");
  await page.goto("/?page=setups");
  await expect(page.locator(".run-btn")).toHaveCount(1);
  await page.getByRole("button", { name: "Account" }).click();
  await page.getByRole("menuitem", { name: "Users" }).click();
  await expect(page.locator(".users-table")).toContainText("Local user");
  await expect(page.getByRole("link", { name: "⭳ Download CSV" })).toHaveAttribute("href", "/api/admin/users.csv");
});
