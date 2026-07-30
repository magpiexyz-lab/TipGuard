# Demo-Mode Dev-Server Startup

Canonical reference for the demo-mode dev-server startup snippet used by
verification procedures (`design-critic`, `ux-journeyer`,
`accessibility-scanner`, `behavior-verifier`). Each procedure inlines the
snippet with a concrete port so the procedure stays JIT-self-contained;
this file documents the canonical form so edits to the env vars, poll
timeout, or abort behavior are reconciled in one place first, then
propagated.

> **Single source of truth.** The four procedures listed below MUST inline
> a textually equivalent snippet — only the port number varies. Drift in
> the env vars, timeout, or abort behavior should be reconciled here
> first, then propagated. **Enforced by `scripts/consistency-check.sh`
> Check 24** — fails CI on port drift, missing REF line, or any
> unregistered procedure that inlines `DEMO_MODE=true ... npm run start`.

## Canonical Snippet

```bash
DEMO_MODE=true NEXT_PUBLIC_DEMO_MODE=true npm run start -- -p <PORT> &
```

After starting, poll `http://localhost:<PORT>` (or the provided
`base_url`) until it responds. **Max 15 seconds**, then abort the
procedure.

## Components

| Element | Value | Why |
|---|---|---|
| Env var | `DEMO_MODE=true` | Server-side demo fixtures / external-call disable |
| Env var | `NEXT_PUBLIC_DEMO_MODE=true` | Client-side demo flag (Next.js public env) |
| Command | `npm run start` | Production-mode server (post-build) |
| Flag | `-- -p <PORT>` | Custom port passed through to Next.js |
| Backgrounding | `&` | Releases the procedure to continue with poll |
| Poll target | `http://localhost:<PORT>` | The just-started server |
| Timeout | 15 seconds | Bound on first-response latency |
| Failure mode | Abort the procedure | If poll exceeds timeout, do not proceed |

## Port Allocation

| Procedure | Port |
|---|---|
| `.claude/procedures/accessibility-scanner.md` | 3096 |
| `.claude/procedures/behavior-verifier.md` | 3097 |
| `.claude/procedures/ux-journeyer.md` | 3098 |
| `.claude/procedures/design-critic.md` | 3099 |

Ports are chosen distinct so concurrent agents do not clash. New
procedures should pick the next free port in the 309x range.
