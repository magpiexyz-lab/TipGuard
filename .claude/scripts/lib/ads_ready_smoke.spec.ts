// ads_ready_smoke.spec.ts - synthetic-gclid PostHog smoke test driver.
import { test } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

const DEPLOY_URL = process.env.ADS_READY_DEPLOY_URL!;
const SYNTHETIC_GCLID = process.env.ADS_READY_GCLID!;
const UTM_CAMPAIGN = process.env.ADS_READY_UTM_CAMPAIGN!;
const OUTPUT_DIR = process.env.ADS_READY_OUTPUT_DIR!;

test("synthetic gclid produces PostHog ingest diagnostic", async ({ page }) => {
  const captured: Array<{
    event: string | undefined;
    gclid: string | undefined;
    project_name: string | undefined;
    utm_campaign: string | undefined;
    ts: number;
  }> = [];

  page.on("request", async (req) => {
    const url = req.url();
    if (!url.includes("/ingest") && !url.includes("i.posthog.com")) {
      return;
    }

    try {
      const postData = req.postData();
      if (!postData) {
        return;
      }
      const body = JSON.parse(postData);
      const events = Array.isArray(body.batch) ? body.batch : [body];
      for (const ev of events) {
        captured.push({
          event: ev.event,
          gclid: ev.properties?.gclid ?? ev.properties?.$session_entry_gclid,
          project_name: ev.properties?.project_name,
          utm_campaign: ev.properties?.utm_campaign,
          ts: Date.now(),
        });
      }
    } catch {
      // Diagnostic capture is best effort. The Python HogQL check is authoritative.
    }
  });

  await page.goto(`${DEPLOY_URL}/?gclid=${SYNTHETIC_GCLID}&utm_campaign=${UTM_CAMPAIGN}`, {
    waitUntil: "domcontentloaded",
    timeout: 30000,
  });

  const deadline = Date.now() + 15000;
  while (Date.now() < deadline && captured.length === 0) {
    await page.waitForTimeout(500);
  }

  await page.waitForTimeout(3000);

  // Navigate away to flush $pageleave before teardown. Check 24 (attribution
  // universality) needs at least one SDK auto-event among the probe's rows;
  // with capture_pageview disabled, $pageleave is the only auto-event a
  // no-interaction probe visit reliably produces, and it only fires on unload.
  await page.goto("about:blank");
  await page.waitForTimeout(2000);

  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  fs.writeFileSync(
    path.join(OUTPUT_DIR, "captured-events.json"),
    JSON.stringify(
      {
        captured,
        deploy_url: DEPLOY_URL,
        gclid: SYNTHETIC_GCLID,
        utm_campaign: UTM_CAMPAIGN,
        note: "Diagnostic only. Empty captured array does not imply failure; Python HogQL verification is authoritative.",
      },
      null,
      2,
    ),
  );
});
