import { test, expect } from "@playwright/test";
import { getTestCredentials, login, captureAnalytics, type CapturedEvent } from "./helpers";

/**
 * The golden path, in order:
 *   landing (landing_view) -> CTA (cta_click) -> /score (score_completed)
 *   -> /signup (signup_complete) -> /staff (roster_imported) -> /notices (notice_sent)
 *
 * Auth-gated steps are skipped under DEMO_MODE (#1148): global-setup writes
 * empty credentials when Supabase is unavailable, so those steps would
 * false-fail with no useful signal. Re-run them after `/deploy` or against a
 * real local Supabase.
 */
test.describe.serial("User funnel", () => {
  let analytics: CapturedEvent[];

  test.beforeEach(async ({ page }) => {
    analytics = await captureAnalytics(page);
  });

  test("landing states the tip-credit exposure and offers the score", async ({ page }) => {
    await page.goto("/");
    // The h1 is the variant headline — assert on content, not just presence.
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/tip credit/i);
    // `data-cta` is stable: the CTA appears at least twice on a landing page,
    // so a text selector would trip Playwright strict mode.
    await expect(page.locator('[data-cta="hero"]')).toBeVisible();
  });

  test("primary CTA navigates to the free score", async ({ page }) => {
    await page.goto("/");
    await page.locator('[data-cta="hero"]').first().click();
    await expect(page).toHaveURL(/\/score/);
    await expect(page.getByRole("radiogroup").first()).toBeVisible();
  });

  test("the questionnaire is reachable without a session", async ({ page, context }) => {
    await context.clearCookies();
    await page.goto("/score");
    // Not redirected to /login — /score is a public route.
    await expect(page).toHaveURL(/\/score/);
    await expect(page.getByRole("radio").first()).toBeVisible();
  });

  test("login reaches the dashboard", async ({ page }) => {
    test.skip(
      process.env.DEMO_MODE === "true",
      "DB-dependent — re-run after /deploy or with real Supabase"
    );
    const { email, password } = getTestCredentials();
    test.skip(!email, "No test user was provisioned by global-setup");
    await login(page, email, password);
    await expect(page).toHaveURL(/\/dashboard/);
  });

  test("the roster import surface is reachable when signed in", async ({ page }) => {
    test.skip(
      process.env.DEMO_MODE === "true",
      "DB-dependent — re-run after /deploy or with real Supabase"
    );
    const { email, password } = getTestCredentials();
    test.skip(!email, "No test user was provisioned by global-setup");
    await login(page, email, password);
    await page.goto("/staff");
    await expect(page.getByRole("heading", { name: /import your tipped staff/i })).toBeVisible();
    await expect(page.getByRole("tab", { name: /paste rows/i })).toBeVisible();
  });

  test("the notice ledger is reachable when signed in", async ({ page }) => {
    test.skip(
      process.env.DEMO_MODE === "true",
      "DB-dependent — re-run after /deploy or with real Supabase"
    );
    const { email, password } = getTestCredentials();
    test.skip(!email, "No test user was provisioned by global-setup");
    await login(page, email, password);
    await page.goto("/notices");
    await expect(page).toHaveURL(/\/notices/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/./);
  });

  test("golden-path analytics events fire", async ({ page }) => {
    await page.goto("/");
    await page.locator('[data-cta="hero"]').first().click();
    await expect(page).toHaveURL(/\/score/);

    const fired = analytics.map((event) => event.event);
    for (const expected of ["landing_view", "cta_click"]) {
      expect(fired).toContain(expected);
    }
    // retain_return is deliberately not asserted — it needs a 24h+ gap.
  });
});
