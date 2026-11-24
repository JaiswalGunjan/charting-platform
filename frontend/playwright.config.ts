import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

// End-to-end tests: a seeded synthetic backend on :8010 and a Vite dev server on :5180 proxying to it, so the
// tests never touch the real database or the dev servers on :8000/:5173.
// Locally the installed Microsoft Edge is used (no browser download); CI installs Chromium (PW_BROWSER=chromium).
const API_PORT = 8010;
const WEB_PORT = 5180;
const venvPython = path.resolve(process.cwd(), "..", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const python = (process.env.PYTHON ?? venvPython).split(path.sep).join("/");

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false,
  workers: 1,                    // one shared backend: keep tests independent but sequential
  retries: process.env.CI ? 1 : 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    viewport: { width: 1500, height: 850 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{
    name: "browser",
    use: process.env.PW_BROWSER === "chromium" ? { ...devices["Desktop Chrome"], viewport: { width: 1500, height: 850 } }
      : { ...devices["Desktop Edge"], channel: "msedge", viewport: { width: 1500, height: 850 } },
  }],
  webServer: [
    {
      command: `"${python}" tests/e2e/serve_backend.py`,
      url: `http://127.0.0.1:${API_PORT}/health`,
      timeout: 180_000,
      reuseExistingServer: false,
      env: { E2E_API_PORT: String(API_PORT) },
    },
    {
      command: "npx vite --host 127.0.0.1",
      url: `http://127.0.0.1:${WEB_PORT}`,
      timeout: 60_000,
      reuseExistingServer: false,
      env: { PORT: String(WEB_PORT), API_TARGET: `http://127.0.0.1:${API_PORT}` },
    },
  ],
});
