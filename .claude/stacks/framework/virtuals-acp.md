---
assumes: []
packages:
  runtime: ["@anthropic-ai/sdk", zod]
  dev: [typescript, tsx, "@types/node", "eslint@9", "@eslint/js", typescript-eslint]
files:
  - .nvmrc
  - eslint.config.mjs
  - src/index.ts
env:
  server: [WHITELISTED_WALLET_PRIVATE_KEY, WHITELISTED_WALLET_ENTITY_ID, AGENT_WALLET_ADDRESS]
  client: []
ci_placeholders: {}
clean:
  files: []
  dirs: []
gitignore: []
---
# Framework: Virtuals ACP
> Used when experiment.yaml has `stack.services[].runtime: virtuals-acp`
> Assumes: nothing (standalone persistent-process agent)

## Packages
```bash
npm install @anthropic-ai/sdk zod
npm install -D typescript tsx @types/node eslint@9 @eslint/js typescript-eslint
# Pin eslint@9 — flat config required; update all 4 framework stack files when eslint 10 ships
```

The `@virtuals-protocol/acp-node` package provides the ACP client and contract
interaction layer. Install it separately as it requires wallet credentials at
import time:

```
npm install @virtuals-protocol/acp-node
```

> **Note:** The ACP Node SDK is under active development. Package name, exports,
> and API surface may change between versions. Pin the version in package.json
> after bootstrap and check the repo for breaking changes before upgrading:
> `github.com/Virtual-Protocol/acp-node`

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
> The `^_` ignore lets you mark intentionally unused params as `_userId` without tripping `no-unused-vars` — standard TS/ESLint convention.

## File Structure
```
src/
  index.ts          # Entry point — ACP client init, onNewTask callback, polling
  handlers/         # One file per experiment.yaml endpoint, dispatched by job type
    <endpoint>.ts   # Handler module
  lib/              # Utilities (analytics, LLM clients, etc.)
    analytics.ts    # Server-side analytics (see analytics stack file)
```

- No `src/app/` directory — ACP agents are not HTTP servers
- No `src/components/` — agents have no UI
- No `pages/`, no React, no JSX
- No HTTP framework (Hono, Express) — the ACP SDK manages task polling

## Entry Point

### `src/index.ts` — Application entry point
```ts
import { AcpClient } from "@virtuals-protocol/acp-node";

const client = new AcpClient({
  walletPrivateKey: process.env.WHITELISTED_WALLET_PRIVATE_KEY!,
  entityId: Number(process.env.WHITELISTED_WALLET_ENTITY_ID!),
  agentWalletAddress: process.env.AGENT_WALLET_ADDRESS!,
});

// Register task handler — dispatches to handler modules by job type
client.onNewTask(async (task) => {
  const jobType = task.taskDescription?.toLowerCase() ?? "";

  // Dispatch to handlers based on experiment.yaml endpoints
  // Example: if (jobType.includes("analyze-token")) { ... }

  // Return result to ACP protocol
  return { success: true, result: "Task completed" };
});

// Start polling for new tasks
client.start();
console.log("ACP agent started — polling for tasks");
```
- `client.start()` begins a persistent polling loop — the process runs indefinitely
- Each incoming task is dispatched to a handler module based on the job type string
- The agent must be registered on the ACP protocol before receiving tasks (see Offering Registration below)

## Handler Conventions

Each endpoint in experiment.yaml gets a handler file in `src/handlers/`:

```ts
// src/handlers/analyze-token.ts
import { z } from "zod";

const AnalyzeTokenInput = z.object({
  tokenAddress: z.string().regex(/^0x[a-fA-F0-9]{40}$/),
  chain: z.string().default("base"),
});

export async function analyzeToken(taskData: unknown) {
  const parsed = AnalyzeTokenInput.safeParse(taskData);
  if (!parsed.success) {
    return { success: false, error: parsed.error.flatten() };
  }
  const { tokenAddress, chain } = parsed.data;
  // Business logic here — API calls, analysis, LLM narrative, etc.
  return { success: true, result: { tokenAddress, chain, risk: "low" } };
}
```

Register handlers in `src/index.ts`:
```ts
import { analyzeToken } from "./handlers/analyze-token";

client.onNewTask(async (task) => {
  const jobType = task.taskDescription?.toLowerCase() ?? "";
  if (jobType.includes("analyze-token")) {
    return analyzeToken(task.taskData);
  }
  // ... additional handlers
  return { success: false, error: "Unknown job type" };
});
```

- Each handler file exports a single async function
- Validate all input with zod — `safeParse` for structured error responses
- Return `{ success: boolean, result?: any, error?: any }`
- Handler dispatch is by job type string matching (not URL routing)

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

## Environment Variables

```
WHITELISTED_WALLET_PRIVATE_KEY=  # Private key of the whitelisted wallet (hex)
WHITELISTED_WALLET_ENTITY_ID=    # Entity ID assigned by ACP protocol
AGENT_WALLET_ADDRESS=            # Public address of the agent wallet
```

> **Note:** Exact env var names may vary between SDK versions. Check the
> `@virtuals-protocol/acp-node` README for the current expected names.
> These are real blockchain wallet credentials — there are no test/sandbox
> equivalents. CI builds cannot placeholder these values (hence
> `ci_placeholders: {}` in frontmatter).

## Offering Registration

ACP agents must register an "offering" on the Virtuals Protocol before they can
receive tasks from other agents. This is done via the web UI, not programmatically:

1. Go to `app.virtuals.io/acp/join`
2. Connect the agent wallet
3. Fill in the offering details: name, description, pricing, accepted job types
4. Submit the registration transaction

The offering defines what tasks the agent accepts and at what price. Once
registered, other ACP agents can discover and assign tasks to this agent.

## Payment

Payment is native to the ACP protocol — no separate `payment/` stack file needed.

- When an agent completes a task, the ACP protocol handles payment automatically
- Default split: 80% to the service agent, 20% to the protocol
- Payment is in USDC on the Base chain
- Pricing is set in the offering registration (see above)
- No Stripe, no checkout flow, no webhook — payment settlement is on-chain

When `stack.analytics` is present: track payment events using `trackServerEvent()`
(e.g., `task_completed` with `amount_usdc` property) rather than
`pay_start`/`pay_success`, which assume a web checkout flow. Skip analytics tracking if `stack.analytics` is absent.

## Data Fetching
- All logic is server-side (persistent Node.js process)
- Use `fetch` for external API calls in handlers
- For parallel API calls with graceful degradation, use `Promise.allSettled`:
  ```ts
  const results = await Promise.allSettled([
    fetchTokenData(address),
    fetchDeployerInfo(address),
    fetchLiquidityData(address),
  ]);
  // Process settled results — failed calls return fallback data, not errors
  ```

## Restrictions
- No React, no JSX — ACP agents are pure TypeScript
- No HTTP server framework — the ACP SDK manages task polling
- No file-system routing — handlers are dispatched by job type string
- No `"use client"` directive — everything is server-side
- No landing page, no UI components, no `src/app/` directory

## Security
- Wallet private keys are extremely sensitive — never log, never expose in errors
- Validate all task input with zod before processing
- Never expose internal error details in task results — return generic error messages
- Use environment variables for all secrets (wallet keys, API keys for external services)
- Rate limiting is not applicable — the ACP protocol controls task assignment rate

## Patterns
- One handler file per experiment.yaml endpoint in `src/handlers/`
- Dispatch tasks in `src/index.ts` based on job type string
- Use zod for all input validation
- Return structured `{ success, result?, error? }` from every handler
- Use `tsx watch` for development, `tsc` for production builds
- For LLM narrative generation, use the Anthropic SDK (`@anthropic-ai/sdk`)

## PR Instructions
- No additional framework setup needed after merging — `npm install && npm run dev` is sufficient
- Offering registration must be completed on `app.virtuals.io/acp/join` before the agent can receive tasks
- Wallet credentials must be configured in `.env.local` before running locally
