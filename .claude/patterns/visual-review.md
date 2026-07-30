# Visual Review Infrastructure

Technical reference for screenshotting pages. The `design-critic` agent
follows this procedure for server setup, demo mode rebuild, and screenshots.

> Requires Playwright. Skips automatically when not installed.

## 1. Prerequisite Check

Run `npx playwright --version`. If it fails (not installed), skip this
entire procedure with the message:

> Skipping visual review — Playwright not installed.

## 1b. Rebuild with demo mode

Rebuild with `NEXT_PUBLIC_DEMO_MODE=true` so all external service clients
(Supabase, Stripe, Resend) return mock responses instead of crashing on
placeholder credentials. This rebuild is for visual review only — it is
not committed.

```bash
env_file=/tmp/.env.visual-review
echo 'NEXT_PUBLIC_DEMO_MODE=true' > "$env_file"
grep 'NEXT_PUBLIC_' .env.example 2>/dev/null | sed 's/=.*/=placeholder/' >> "$env_file" || true
set -a && . "$env_file" && set +a && npm run build
rm "$env_file"
```

## 2. Start Production Server

The build has already passed at this point. Start a production server on a
non-conflicting port:

```bash
DEMO_MODE=true NEXT_PUBLIC_DEMO_MODE=true npm run start -- -p 3099 &
```

Poll `http://localhost:3099` until it responds (max 15 seconds, then abort).

## 3. Screenshot All Pages

Read `experiment/experiment.yaml` to get the list of pages and their routes. Write a
small inline Node.js script that uses the Playwright API to:

- Launch a Chromium browser (headless)
- Visit each route at `http://localhost:3099`
- Wait for network idle
- Take a full-page screenshot at **1280x800** viewport (desktop)
- Save to `/tmp/visual-review/<page-name>.png`
- Take a second full-page screenshot at **375x812** viewport (mobile)
- Save to `/tmp/visual-review/<page-name>-mobile.png`

Run the script with `node`.

## 4. Cleanup

Kill the production server and remove the temporary screenshots:

```bash
kill %1 2>/dev/null || true
rm -rf /tmp/visual-review
```
