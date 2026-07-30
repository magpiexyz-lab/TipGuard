---
assumes: []
packages:
  runtime: [commander]
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
# Framework: Commander.js
> Used when experiment.yaml has `stack.services[].runtime: commander`
> Assumes: nothing (standalone CLI tool)

## Packages
```bash
npm install commander
npm install -D typescript tsx @types/node eslint@9 @eslint/js typescript-eslint
# Pin eslint@9 — flat config required; update all 4 framework stack files when eslint 10 ships
```

## Project Setup
- `.nvmrc`: containing `20` (used by CI and local version managers)
- `package.json`: `name` from experiment.yaml, `bin` field pointing to `dist/index.js`, `scripts` with `dev`, `build`, `start`, `lint`, and `test` (when `stack.testing` is present); `engines: { "node": ">=20" }`
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
  index.ts          # Entry point — sets up program, registers commands, calls parse()
  commands/         # One file per experiment.yaml command
    <command>.ts    # Command module
  lib/              # Utilities (analytics, etc.)
    analytics.ts    # Server-side analytics (see analytics stack file)
```

- No `src/app/` directory — CLIs do not use file-system routing
- No `src/components/` — CLIs have no UI
- No `pages/`, no React, no JSX, no HTTP server

## Entry Point

### `src/index.ts` — CLI entry point
```ts
#!/usr/bin/env node
import { Command } from "commander";

const program = new Command();

program
  .name("my-cli")
  .description("CLI description from experiment.yaml")
  .version("0.1.0");

// Register command modules here (one per experiment.yaml command)
// Example: import { registerDeployCommand } from "./commands/deploy";
// registerDeployCommand(program);

program.parse();
```
- The shebang (`#!/usr/bin/env node`) is required for the `bin` field to work
- `program.parse()` reads `process.argv` and dispatches to the matching command
- Each command module registers itself on the `program` instance

## Command Conventions

Each command in experiment.yaml gets a command file in `src/commands/`:

```ts
// src/commands/deploy.ts
import { Command } from "commander";

export function registerDeployCommand(program: Command) {
  program
    .command("deploy")
    .description("Deploy a service to the platform")
    .argument("<target>", "deployment target")
    .option("-e, --env <environment>", "target environment", "production")
    .action(async (target, options) => {
      // Business logic here
      console.log(`Deploying ${target} to ${options.env}`);
    });
}
```

Register commands in `src/index.ts`:
```ts
import { registerDeployCommand } from "./commands/deploy";
registerDeployCommand(program);
```

- Each command file exports a `register<Name>Command(program)` function
- Use `.argument()` for positional args and `.option()` for flags
- Use `.action(async (args, options) => { ... })` for the handler
- Print output to stdout; print errors to stderr
- Exit with `process.exit(1)` on failure

## package.json Scripts
```json
{
  "dev": "tsx src/index.ts",
  "build": "tsc",
  "start": "node dist/index.js",
  "lint": "eslint src/"
}
```

- `dev` runs the CLI directly via `tsx` (no compilation step during development)
- `build` compiles TypeScript to `dist/` via `tsc`
- `start` runs the compiled output
- When `stack.testing: vitest` is present, add `"test": "vitest run"`

## package.json Bin Field
```json
{
  "bin": {
    "my-cli": "dist/index.js"
  }
}
```
Replace `my-cli` with experiment.yaml `name`. After `npm link` or `npm install -g`,
the CLI is available as a global command.

## Data Fetching
- All logic runs in Node.js on the user's machine
- Use `fetch` for external API calls
- For file operations, use `node:fs/promises`
- For user prompts, use `@inquirer/prompts` (add to dependencies if needed)

## Restrictions
- No React, no JSX — CLIs are pure TypeScript
- No HTTP server — CLIs are run-and-exit processes
- No file-system routing — commands are registered explicitly
- No `"use client"` directive — everything runs in Node.js
- No landing page, no UI components, no `src/app/` directory

## Security
- Never store secrets in the compiled binary
- If the CLI needs credentials, read from environment variables or a config file
- Validate all user input before processing
- If making network requests, validate URLs and sanitize paths

## Patterns
- One command file per experiment.yaml command in `src/commands/`
- Register all commands in `src/index.ts` with `register<Name>Command(program)`
- Use `commander` for argument parsing — no custom argv parsing
- Print structured output (JSON) when `--json` flag is present
- Use `tsx` for development, `tsc` for production builds
- Test commands by importing the register function and using `program.parseAsync()`

## PR Instructions
- No additional framework setup needed after merging — `npm install && npm run dev` is sufficient
- To test locally as a global CLI: `npm run build && npm link`
