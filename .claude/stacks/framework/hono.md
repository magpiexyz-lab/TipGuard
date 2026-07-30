---
assumes: []
packages:
  runtime: [hono, "@hono/node-server"]
  dev: [typescript, tsx, "@types/node", "eslint@9", "@eslint/js", typescript-eslint]
files:
  - .nvmrc
  - eslint.config.mjs
  - src/index.ts
env:
  server: []
  client: []
ci_placeholders: {}
clean:
  files: []
  dirs: []
gitignore: []
---
# Framework: Hono
> Used when experiment.yaml has `stack.services[].runtime: hono`

## Packages
```bash
npm install hono @hono/node-server
npm install -D typescript tsx @types/node eslint@9 @eslint/js typescript-eslint
# Pin eslint@9 — flat config required; update all 4 framework stack files when eslint 10 ships
```

## Project Setup
- `.nvmrc`: containing `20` (used by CI and local version managers)
- `package.json`: `scripts` with `dev`, `build`, `start`, `lint`, and `test` (when `stack.testing` is present); `engines: { "node": ">=20" }`
- `tsconfig.json`: enable `strict: true`, target `ES2022`, module `NodeNext`, outDir `dist`, `@/` path alias mapping to `src/`

### `eslint.config.mjs`
```js
import eslint from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          destructuredArrayIgnorePattern: "^_",
          ignoreRestSiblings: true,
        },
      ],
    },
  },
  { ignores: ["dist/", "node_modules/"] }
);
```
> The `^_` ignore lets you mark intentionally unused params as `_userId` without tripping `no-unused-vars` — without it, route handlers with unused callback args fail `npm run lint`.

## File Structure
```
src/
  index.ts          # Entry point — creates Hono app, registers routes, serves
  routes/           # One file per experiment.yaml endpoint
    <endpoint>.ts   # Route handler module
  lib/              # Utilities (analytics, database clients, etc.)
    analytics.ts    # Server-side analytics (see analytics stack file)
```

- No `src/app/` directory — Hono does not use file-system routing
- No `src/components/` — services have no UI
- No `pages/`, no React, no JSX

## Entry Point

### `src/index.ts` — Application entry point
```ts
import { Hono } from "hono";
import { serve } from "@hono/node-server";

const app = new Hono();

// Health check — always present
app.get("/api/health", (c) => {
  return c.json({ status: "ok" });
});

// When surface is co-located: add root route returning HTML marketing page
// Example: app.get("/", (c) => c.html("<!DOCTYPE html>..."));

// Register route modules here (one per experiment.yaml endpoint)
// Example: app.route("/api/convert", convertRoute);

const port = Number(process.env.PORT) || 3000;
console.log(`Server running on port ${port}`);
serve({ fetch: app.fetch, port });

export default app;
```
- `export default app` enables testing via `app.request()` without starting the server
- `process.env.PORT` for Railway/container hosting compatibility
- Health check is inline — additional service checks added by bootstrap based on active stack (same pattern as hosting stack file)

## Route Conventions

Each endpoint in experiment.yaml gets a route file in `src/routes/`:

```ts
// src/routes/convert.ts
import { Hono } from "hono";
import { z } from "zod";

const route = new Hono();

const ConvertSchema = z.object({
  from: z.string().length(3),
  to: z.string().length(3),
  amount: z.number().positive(),
});

route.post("/", async (c) => {
  const body = await c.req.json();
  const parsed = ConvertSchema.safeParse(body);
  if (!parsed.success) {
    return c.json({ error: parsed.error.flatten() }, 400);
  }
  const { from, to, amount } = parsed.data;
  // Business logic here
  return c.json({ from, to, amount, result: amount * 0.85 });
});

export default route;
```

Register routes in `src/index.ts`:
```ts
import convertRoute from "./routes/convert";
app.route("/api/convert", convertRoute);
```

- Each route file exports a `Hono` instance (route group)
- Validate all input with zod — `safeParse` for structured error responses
- Return `c.json({ error: ... }, status)` for errors
- Route prefix (`/api/convert`) is set at registration, not in the route file

## package.json Scripts
```json
{
  "dev": "tsx watch src/index.ts",
  "build": "tsc",
  "start": "node dist/index.js",
  "lint": "eslint src/"
}
```

- `dev` uses `tsx watch` for hot-reload during development
- `build` compiles TypeScript to `dist/` via `tsc`
- `start` runs the compiled output (production)
- When `stack.testing: vitest` is present, add `"test": "vitest run"`

## Data Fetching
- All data access is server-side (no client components)
- Use the database client directly in route handlers
- For external APIs, use `fetch` in route handlers

## Restrictions
- No React, no JSX — Hono services are pure TypeScript
- No `"use client"` directive — everything is server-side
- No file-system routing — routes are registered explicitly in `src/index.ts`
- No Server Actions, no middleware chains — use simple route handlers

## Security
- Validate all request input with zod before processing
- Never expose internal error details — use the global error handler below
- Use environment variables for all secrets
- When `stack.database` is present, enforce access control in route handlers (no RLS available in non-Postgres databases)
- Rate limiting: use in-memory counters for auth and payment routes (works on persistent-process hosts like Railway)

### Global Error Handler

Add to `src/index.ts` after route registrations:

```ts
app.onError((err, c) => {
  console.error("Unhandled error:", err);
  return c.json(
    { error: "Internal server error", message: "An unexpected error occurred. Please try again." },
    500
  );
});
```

This catches unhandled exceptions in route handlers and returns a generic error response. The full error is logged server-side for debugging but never exposed to the client.

## CORS

When the service is called from a browser (e.g., from a landing page or external client), add CORS middleware:

```ts
import { cors } from "hono/cors";

app.use("*", cors({
  origin: process.env.CORS_ORIGIN || "http://localhost:3000",
}));
```

- Use an environment variable for the allowed origin — never use `"*"` in production
- Place `app.use("*", cors(...))` before route registrations in `src/index.ts`
- `hono/cors` is included with the `hono` package — no additional install needed

## Patterns
- One route file per experiment.yaml endpoint in `src/routes/`
- Register all routes in `src/index.ts` with `app.route("/api/<name>", route)`
- Use `c.json()` for all responses
- Use `c.req.json()` to parse request bodies, then validate with zod
- Export `app` from `src/index.ts` for testing via `app.request()`
- Use `tsx watch` for development, `tsc` for production builds

## PR Instructions
- No additional framework setup needed after merging — `npm install && npm run dev` is sufficient
