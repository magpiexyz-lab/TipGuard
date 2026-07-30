#!/usr/bin/env node
/*
 * consistency_dom_extract.js — Lead-side DOM feature extractor (#1257).
 *
 * Renders each page via Playwright and extracts deterministic structural
 * features (header/footer/nav/sidebar presence, content width, h1 count).
 * Output is a JSON manifest the lead-side prepass consumes to compute
 * cross-page anomaly candidates without running any agent.
 *
 * This script replaces the agent-side C5 screenshot+compare loop that
 * caused #1257 exhaustion: under page-batching, the lead does this
 * deterministic work once, then each batch agent only judges severity.
 *
 * Usage:
 *   node .claude/scripts/lib/consistency_dom_extract.js \
 *     --base-url http://localhost:3000 \
 *     --pages-json '[{"name":"home","test_url":"/"}, ...]' \
 *     --output .runs/consistency-check-dom-features.json
 *
 * Exit codes:
 *   0 — all pages processed (per-page errors recorded as `{name, error}` entries)
 *   1 — fatal error (Playwright unavailable, output write failed, etc.)
 *
 * Per-page failure isolation: a single page's render failure does not
 * abort the whole pass — it emits an `error` entry so the prepass can
 * fall back to static analysis for that page.
 */

const fs = require('fs');

function parseArgs(argv) {
  const args = { baseUrl: null, pagesJson: null, output: null };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--base-url') args.baseUrl = argv[++i];
    else if (a === '--pages-json') args.pagesJson = argv[++i];
    else if (a === '--output') args.output = argv[++i];
  }
  if (!args.baseUrl || !args.pagesJson || !args.output) {
    console.error('Usage: node consistency_dom_extract.js --base-url <url> --pages-json <json> --output <path>');
    process.exit(1);
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv);
  let chromium;
  try {
    ({ chromium } = require('playwright'));
  } catch (err) {
    console.error('consistency_dom_extract: playwright not available:', err.message);
    process.exit(1);
  }

  let pages;
  try {
    pages = JSON.parse(args.pagesJson);
  } catch (err) {
    console.error('consistency_dom_extract: invalid --pages-json:', err.message);
    process.exit(1);
  }

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const features = [];

  for (const p of pages) {
    const page = await ctx.newPage();
    try {
      await page.goto(`${args.baseUrl}${p.test_url}`, {
        waitUntil: 'networkidle',
        timeout: 30000,
      });
      const f = await page.evaluate(() => ({
        header_present: !!document.querySelector('header, [role="banner"]'),
        footer_present: !!document.querySelector('footer, [role="contentinfo"]'),
        nav_present: !!document.querySelector('nav, [role="navigation"]'),
        sidebar_present: !!document.querySelector('aside, [role="complementary"]'),
        content_width: Math.round(
          document.querySelector('main')?.getBoundingClientRect()?.width || 0
        ),
        h1_count: document.querySelectorAll('h1').length,
      }));
      features.push({ name: p.name, ...f });
    } catch (err) {
      features.push({ name: p.name, error: String(err && err.message || err) });
    } finally {
      await page.close();
    }
  }

  await browser.close();

  fs.writeFileSync(
    args.output,
    JSON.stringify({
      generated_at: new Date().toISOString(),
      base_url: args.baseUrl,
      features,
    }, null, 2)
  );
  console.log(`consistency_dom_extract: wrote ${args.output} (${features.length} pages)`);
}

main().catch((err) => {
  console.error('consistency_dom_extract: fatal:', err);
  process.exit(1);
});
