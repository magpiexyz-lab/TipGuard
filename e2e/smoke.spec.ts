import { test, expect } from "@playwright/test";
import { blockAnalytics, checkNoHorizontalOverflow } from "./helpers";

/**
 * Page-load smoke tests — one per page in `derive_scope_pages(experiment)`
 * plus one per variant route. These verify a page renders without a runtime
 * error, nothing more. The user journey is `funnel.spec.ts`; per-behavior
 * correctness is `behaviors.spec.ts`.
 *
 * Auth-gated routes (/dashboard, /staff, /notices, /violations, /audit-file)
 * redirect to /login for an anonymous visitor. That is a successful load, so
 * the title assertion still holds — the point here is "no crash", not "no
 * redirect".
 */
test.describe.serial("Funnel smoke test", () => {
  test.beforeEach(async ({ page }) => {
    await blockAnalytics(page);
  });

  test("landing loads", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  test("score loads", async ({ page }) => {
    await page.goto("/score");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  test("signup loads", async ({ page }) => {
    await page.goto("/signup");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  test("login loads", async ({ page }) => {
    await page.goto("/login");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  test("dashboard loads", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  test("staff loads", async ({ page }) => {
    await page.goto("/staff");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  test("notices loads", async ({ page }) => {
    await page.goto("/notices");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  test("sign loads", async ({ page }) => {
    await page.goto("/sign");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  test("violations loads", async ({ page }) => {
    await page.goto("/violations");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  test("pricing loads", async ({ page }) => {
    await page.goto("/pricing");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  test("audit-file loads", async ({ page }) => {
    await page.goto("/audit-file");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  test("auth reset-password loads", async ({ page }) => {
    await page.goto("/auth/reset-password");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  // --- Variant landings (one ad group each) ---

  test("variant audit-risk loads", async ({ page }) => {
    await page.goto("/v/audit-risk");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  test("variant cost-shield loads", async ({ page }) => {
    await page.goto("/v/cost-shield");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  test("variant one-click-file loads", async ({ page }) => {
    await page.goto("/v/one-click-file");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  test("health endpoint answers", async ({ request }) => {
    const response = await request.get("/api/health");
    expect([200, 503]).toContain(response.status());
    const body = await response.json();
    expect(body).toHaveProperty("status");
  });
});
