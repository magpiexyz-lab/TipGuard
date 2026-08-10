#!/usr/bin/env node
// Validates analytics configuration before build, on hosting platforms only.
// Runs as `prebuild` lifecycle hook. Skips on bootstrap/local builds.

import nextEnv from "@next/env";
import fs from "node:fs";

// .mjs (raw Node ESM) requires DEFAULT-import + destructure for @next/env. The
// named-import form (`import { loadEnvConfig } from ...`) fails under Node 22
// raw ESM with `SyntaxError: Named export 'loadEnvConfig' not found` because
// Node's CJS named-export detection does not surface this package's exports.
// .ts files loaded by Playwright/jest/tsx (CJS-transpile via pirates) require
// the OPPOSITE shape — see analytics/posthog.md Stack Knowledge "CJS-interop
// with @next/env" for the per-loader contract.
const { loadEnvConfig } = nextEnv;

// Load .env.local / .env so local `npm run build` invocations see the same
// NEXT_PUBLIC_POSTHOG_KEY override that Next.js itself uses. On Vercel build
// platforms env vars are already populated, so this is a no-op there.
loadEnvConfig(process.cwd());

// Skip-gate: only run on real Vercel/Railway build platforms.
// `process.env.CI === "1"` distinguishes Vercel CI builds from local `vercel build`,
// which also sets VERCEL=1 but not CI=1.
const isVercelBuildPlatform = process.env.CI === "1" && process.env.VERCEL === "1";
const isRailwayBuildPlatform = !!process.env.RAILWAY_ENVIRONMENT_NAME;
if (!isVercelBuildPlatform && !isRailwayBuildPlatform) process.exit(0);

const PLACEHOLDER = "phc_TEAM_KEY";
const envKey = process.env.NEXT_PUBLIC_POSTHOG_KEY ?? "";

// Path 1: env override is valid → pass.
if (envKey && envKey !== PLACEHOLDER) process.exit(0);

// Path 2: env unset/placeholder → check if source has a real fallback.
const SOURCE_PATHS = [
  "src/lib/analytics.ts",
  "src/lib/analytics-server.ts",
  "src/app/route.ts",   // service co-located surface
  "site/index.html",    // cli detached surface
];

const filesWithPlaceholder = SOURCE_PATHS
  .filter(p => fs.existsSync(p))
  .filter(p => {
    const src = fs.readFileSync(p, "utf8");
    return src.includes(`"${PLACEHOLDER}"`) || src.includes(`'${PLACEHOLDER}'`);
  });

if (filesWithPlaceholder.length === 0) process.exit(0);  // source customized → pass

console.error(`\n[analytics] PostHog is not configured for this deployment.`);
console.error(`Files still containing the '${PLACEHOLDER}' placeholder:`);
for (const p of filesWithPlaceholder) console.error(`  - ${p}`);
console.error(`\nFix one of:`);
console.error(`  1. Set NEXT_PUBLIC_POSTHOG_KEY in your hosting platform`);
console.error(`     (Vercel → Project → Settings → Environment Variables).`);
console.error(`  2. Replace '${PLACEHOLDER}' in the listed source files with`);
console.error(`     your team's PostHog publishable key (phc_xxx).\n`);
process.exit(1);
