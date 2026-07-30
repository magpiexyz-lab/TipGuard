---
assumes: []
packages:
  runtime: []
  dev: []
files: []
env:
  server: []
  client: []
ci_placeholders: {}
clean:
  files: []
  dirs: []
gitignore: []
---
# Hosting: Railway
> Used when experiment.yaml has `stack.hosting: railway`
> Assumes: nothing (framework-agnostic — works with any Node.js framework)

## Deployment

Railway supports two deployment modes:

1. **Nixpacks (default)** — auto-detects Node.js, installs dependencies, runs `npm run build`, then `npm start`. Zero config needed.
2. **Dockerfile** — for custom builds, place a `Dockerfile` in the project root. Railway auto-detects and uses it.

### Manual Deploy (CLI)
```bash
railway up
```

### Production Deploys Are Manual
- Production deploys are triggered by re-running `/deploy` (which runs `railway up --detach`)
- GitHub auto-deploy integration is **not connected** — this avoids unnecessary builds and keeps costs predictable
- `make deploy` remains available for manual CLI deploys

## Health Check

The health check endpoint lives at `/api/health` (or the framework's equivalent route). The **framework stack file** creates the actual handler — Railway just needs to know the URL.

**Railway health check config** (set in dashboard or `railway.toml`):
- Health check path: `/api/health`
- Health check timeout: 5s (default)

The health check handler follows the same pattern as other hosting providers — returns binary JSON `{ status: "ok" | "degraded" }` with no per-subsystem keys (prevents infrastructure topology leakage). Detailed check results are logged server-side only. See the hosting/vercel stack file's Health Check section for the response pattern.

## Dockerfile Template

When Nixpacks auto-detect is insufficient (e.g., monorepo, custom build steps), use this Dockerfile:

```dockerfile
FROM node:20-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev
COPY . .
RUN npm run build
EXPOSE ${PORT:-3000}
CMD ["npm", "start"]
```

- `node:20-slim` matches the `.nvmrc` Node version
- `npm ci --omit=dev` installs only production dependencies
- `PORT` is provided by Railway at runtime — the app must listen on `process.env.PORT`

## Environment Variables

Railway injects `PORT` automatically — the app must listen on it. All other env vars are set via:

- **Railway dashboard:** Service → Variables tab
- **Railway CLI:** `railway variables set KEY=VALUE`
- **Shared variables:** Use Railway's shared variables for values used across services

### Framework Considerations
- Railway does NOT use the `NEXT_PUBLIC_` prefix convention — client-side env vars are framework-specific
- For Next.js on Railway: `NEXT_PUBLIC_*` vars must be available at **build time** (set them as Railway variables, not runtime-only secrets)
- For Hono/Express: all env vars are server-side only — no prefix convention needed

## CLI Setup (Non-Interactive)

Used by the `/deploy` skill for automated first-time setup.

### Project Setup
```bash
railway login
railway init          # creates a new project
railway link          # links to existing project
railway service       # select or create a service
```

### Note on GitHub Integration
- GitHub auto-deploy is **not connected** by default — production deploys are manual via `railway up --detach`
- If you want auto-deploy, install the Railway GitHub App manually via Railway dashboard → Project → Settings → GitHub
- Re-running `/deploy` always deploys the latest code regardless of GitHub integration status

### First Deploy
```bash
railway up
```

## Rate Limiting

Unlike serverless platforms, Railway runs persistent processes — in-memory rate limiting works correctly. Use a simple counter map (e.g., `Map<string, number[]>`) for auth and payment API routes.

For high-traffic production use, consider Redis-based rate limiting via a Railway Redis add-on.

## Patterns
- Production deploys are manual — re-run `/deploy` or use `railway up --detach`
- The app must listen on `process.env.PORT` — Railway assigns the port dynamically
- Use Nixpacks for zero-config deploys; add a Dockerfile only when customization is needed
- Environment variables are configured in Railway dashboard or via CLI
- Health check endpoint at `/api/health` is verified by Railway after each deploy
- In-memory rate limiting works on Railway (persistent process, not serverless)

## PR Instructions
- After merging: run `/deploy` in Claude Code to set up Railway automatically. Or manually: create a project at [railway.app](https://railway.app) and add environment variables in the Railway dashboard.
- Production deploys are manual — re-run `/deploy` after code changes to update

## Deploy Interface

Standardized subsections referenced by deploy.md and teardown.md. Each subsection is a self-contained recipe — deploy.md reads them by name and executes the instructions.

### Prerequisites

- **install_check:** `which railway`
- **install_fix:** `npm i -g @railway/cli`
- **auth_check:** `railway whoami`
- **auth_fix:** `railway login`

### Config Gathering

- **CLI command:** `railway whoami` — shows current account info
- Railway uses projects (no team/org concept for selection). No experiment.yaml field needed.

### Project Setup

1. Create a new project (idempotent — reuses if already linked):
   ```bash
   railway init
   ```
   If a project already exists in the directory (`.railway/` config), `railway init` will ask to reuse it.
2. Link to the project:
   ```bash
   railway link
   ```
3. Select or create a service:
   ```bash
   railway service
   ```
4. _(GitHub auto-deploy is not connected — production deploys are manual via `railway up --detach`. See "Note on GitHub Integration" above if you want to enable it later.)_

### Domain Setup

1. Generate a Railway domain:
   ```bash
   railway domain
   ```
   This generates a domain like `<project>.up.railway.app`.
2. For custom domains:
   ```bash
   railway custom-domain add <domain>
   ```
3. **On success:** `canonical_url` = the domain, `domain_added` = true
4. **On failure:** Warn "Could not add domain. Add manually in Railway dashboard → Service → Settings → Domains." Set `canonical_url` = null (finalized after deploy), `domain_added` = false

### Environment Variables

**Primary method — CLI (per-variable):**
```bash
railway variables set KEY=VALUE
```
- No batch API — loop over variables
- No auth token dance needed (CLI handles auth)

**Verify:** `railway variables`

### Volume Setup

Create a persistent volume for databases that need filesystem storage (e.g., SQLite):
```bash
railway volume add --mount <mount_path>
```
- `<mount_path>` comes from the database stack file's `volume_config.mount_path` (e.g., `/data`)
- Set env vars from `volume_config.env_vars` using `railway variables set`

### Deploy

- **Command:** `railway up --detach`
- **Extract URL:** from `railway domain` output (run after deploy completes)

### Health Check

```bash
curl -s <canonical_url>/api/health
```
Returns JSON `{ status: "ok" | "degraded" }` — binary status only, no per-subsystem keys.

### Auto-Fix

| Check | Diagnosis | Fix |
|-------|-----------|-----|
| Env vars | `railway variables` — compare with expected | Re-set via `railway variables set KEY=VALUE`, then redeploy |
| Redeploy | — | `railway up --detach` |

### Teardown

1. Remove project (includes all services, volumes, and domains):
   ```bash
   railway project delete --yes
   ```
2. **Dashboard URL (manual fallback):** `https://railway.app/project/<project_id>`

### Manifest Keys

```json
{
  "provider": "railway",
  "project_id": "<project_id>",
  "domain": "<domain or null>"
}
```

### Rollback

- **Command:** Redeploy previous deployment via dashboard (no single CLI command)
- **Dashboard:** Railway → Deployments → select previous → "Redeploy"
- **Note:** Does NOT rollback database or volume changes.

### Compatibility

- **incompatible_databases:** `[]`
- Railway supports all database types (persistent process with optional volumes)
