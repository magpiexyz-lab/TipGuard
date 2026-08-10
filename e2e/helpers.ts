import { readFileSync } from "fs";
import path from "path";
import type { Page } from "@playwright/test";

const AUTH_FILE = path.join(__dirname, ".auth.json");

export function getTestCredentials() {
  return JSON.parse(readFileSync(AUTH_FILE, "utf-8")) as {
    email: string;
    password: string;
    userId: string;
  };
}

export async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(email);
  await page.locator('input[type="password"]').fill(password);
  await page.locator("form").getByRole("button", { name: /log in|sign in|open my file/i }).click();
  await page.waitForURL((url) => !url.pathname.includes("/login"));
}

export async function blockAnalytics(page: Page) {
  await page.route("**/ingest/**", (route) => route.abort());
}

export interface CapturedEvent {
  event: string;
  properties: Record<string, unknown>;
}

export async function captureAnalytics(page: Page): Promise<CapturedEvent[]> {
  const events: CapturedEvent[] = [];
  await page.route("**/ingest/**", async (route) => {
    try {
      const body = route.request().postDataJSON();
      if (body?.batch) {
        for (const item of body.batch) {
          if (item.event) events.push({ event: item.event, properties: item.properties || {} });
        }
      } else if (body?.event) {
        events.push({ event: body.event, properties: body.properties || {} });
      }
    } catch {
      /* non-JSON body, ignore */
    }
    await route.abort(); // still block from reaching the provider
  });
  return events;
}

export async function checkNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth
  );
  if (overflow) {
    throw new Error(
      `Horizontal overflow detected (scrollWidth ${await page.evaluate(
        () => document.documentElement.scrollWidth
      )}px > clientWidth ${await page.evaluate(
        () => document.documentElement.clientWidth
      )}px)`
    );
  }
}
