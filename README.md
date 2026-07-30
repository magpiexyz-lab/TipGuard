# Experiment Template

![CI](https://github.com/magpiexyz-lab/mvp-template/actions/workflows/ci.yml/badge.svg)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Describe an idea in YAML. Claude Code builds, deploys, and measures it — zero to live MVP with analytics in a single session.**

This is not a starter kit. It's an operating system for Claude Code that encodes the full experiment lifecycle — from hypothesis to production deployment to data-driven iteration — into 16 state-machine skills, 25 specialized agents, and 29 pluggable stack files.

## See it in action

```
> /spec "invoicing tool for freelancers"
✓ Generated experiment/experiment.yaml (L3 full MVP, 4 behaviors, 2 variants)

> /bootstrap
✓ Built app — PR #42 opened: https://github.com/you/quick-bill/pull/42
  → Review and merge the PR

> /verify
✓ 10 agents passed (design, security, UX, accessibility, performance, spec)

> /deploy
✓ Live at https://quick-bill.vercel.app
  Supabase project: quick-bill-prod
  PostHog dashboard ready — share the link and watch the funnel

> /distribute
✓ Generated Google Ads campaign config with 2 variant ad groups

> /iterate
✓ Traction Score: 62 — recommend: refine signup flow (bottleneck at 34% drop-off)
```

## How it works

Every command that writes code shows a plan and waits for your approval before changing anything.

```
    /spec "your idea"  ─or─  edit experiment.yaml manually
                │
       make validate → /bootstrap → merge PR → /verify
                                                    │
                    ┌───────────────────────────────┘
                    │
        ┌───────────┼──────────────┐
        ▼           ▼              ▼
     web-app      service         cli
        │           │              │
   /deploy       /deploy      npm publish
        │           │              │
   /distribute      │              │
   (optional)       │              │
        │           │              │
        └───────────┼──────────────┘
                    │
              Share with users
              Check analytics
                    │
               /iterate
           (recommendations)
                    │
        ┌───────────┼──────────────┐
        ▼           ▼              ▼
   /change                     /retro
   /verify                 (experiment ends)
   merge PR        │              │
        │          │     ┌────────┴────────┐
        └──────────┘     ▼                 ▼
                    /teardown             done
                (web-app / service)      (cli)
```

## Architecture

The system has five layers. Each layer operates independently and communicates through files on disk.

```
┌─────────────────────────────────────────────────────────┐
│  experiment.yaml          Declarative specification      │
├─────────────────────────────────────────────────────────┤
│  16 skills                State-machine orchestrators    │
│  (147 states)             JIT dispatch, one state/step   │
├─────────────────────────────────────────────────────────┤
│  25 agents                Parallel specialized workers   │
│  23 procedures            Agent behavior contracts       │
├─────────────────────────────────────────────────────────┤
│  29 stack files           Pluggable technology adapters  │
│  3 archetypes             Product shape definitions      │
├─────────────────────────────────────────────────────────┤
│  14 hooks                 Runtime enforcement gates      │
│  state-registry.json      Postcondition verification     │
└─────────────────────────────────────────────────────────┘
```

**Declarative specification** — `experiment.yaml` defines what to build: hypotheses, behaviors (given/when/then), golden path, variants, funnel thresholds, and stack choices. Everything downstream reads this file.

**Skill engine** — Each of the 16 skills is a state machine. State files live at `.claude/patterns/<skill>/state-*.md`. The skill reads one state at a time (JIT dispatch), executes it, and advances. Hooks enforce that states complete in order and postconditions pass before the next state begins.

**Agent swarm** — Skills spawn agents for parallel work. `/bootstrap` launches 8 scaffold agents to build the app concurrently. `/verify` runs 10 quality/security agents in parallel. Agents follow procedures (`.claude/procedures/`) that define their exact behavior contracts.

**Stack adapters** — Each technology is a markdown file at `.claude/stacks/<category>/<name>.md` containing setup instructions, code patterns, and constraints. Skills read the active stack files and generate code accordingly. Adding a new technology means adding one file — no skill changes needed.

**Enforcement layer** — 14 shell hooks gate every tool call, commit, and state transition. The state registry (`.claude/patterns/state-registry.json`) maps each state to a postcondition check. Hooks prevent skipping states, committing outside skill flow, or merging unresolved security findings.

## What you get

- **3 archetypes** — web-app, service, cli — each with tailored build, deploy, and test pipelines
- **3 experiment levels** — L1 landing test, L2 interactive MVP, L3 full MVP — match effort to conviction
- **16 slash commands** — from `/spec` through `/teardown`, the full experiment lifecycle
- **29 pluggable stack files** — swap frameworks, databases, hosting, distribution, and more without changing skills
- **25 specialized agents** — design critic, security attacker/defender, UX journeyer, accessibility scanner, and more run across the lifecycle
- **Production quality by default** — TDD, per-task implementer agents, and spec review are always active
- **Full deploy + teardown** — one command to go live, one command to clean up
- **Distribution pipeline** — generate ad campaigns (Google, Meta, Reddit, Twitter) and track through to conversion

## Quick start

1. **Install prerequisites** — Python, Node.js, GitHub CLI. See [docs/prerequisites.md](docs/prerequisites.md).
2. **Spec your idea** — open Claude Code in this repo and run `/spec "your idea"`.
   `/spec` picks the right experiment level automatically, or specify one: L1 (landing), L2 (interactive), L3 (full).
3. **Build, verify, deploy:**
   ```
   /bootstrap      # generates app, opens PR — review and merge
   /verify         # runs 10 agents, auto-fixes failures
   /deploy         # pushes to production
   ```

## Experiment levels

| Level | What it builds | When to use |
|-------|---------------|-------------|
| **L1** Landing test | Landing page measuring interest. No backend. | Unvalidated idea — test demand first |
| **L2** Interactive MVP | Working app with core features and database | Some signal — test usability |
| **L3** Full MVP | Auth, payments, full feature set | High conviction — test willingness to pay |

`/spec` picks the level based on your idea, or you can override it.

## Skills reference

**Build**

| Skill | What it does | Waits for approval? |
|-------|-------------|---------------------|
| `/spec "idea"` | Generate experiment.yaml from a problem statement | Yes |
| `/bootstrap` | Generate the full app from experiment.yaml | Yes |
| `/change [desc]` | Add a feature, fix a bug, polish UI, fix analytics | Yes |
| `/verify` | Run agents and auto-fix failures | No |
| `/resolve` | Resolve GitHub issues filed against the template | Yes |

**Ship**

| Skill | What it does | Waits for approval? |
|-------|-------------|---------------------|
| `/deploy` | Deploy to hosting + database | Yes |
| `/distribute` | Generate ad campaign config and creative assets | Yes |
| `/rollback` | Roll back to previous deployment (emergency) | Yes |
| `/teardown` | Remove all cloud resources | Yes |

**Analyze**

| Skill | What it does | Waits for approval? |
|-------|-------------|---------------------|
| `/iterate` | Analyze metrics, compute Traction Score, recommend next steps | No |
| `/iterate --check` | Monitor active ad campaigns, flag issues | No |
| `/iterate --cross` | Cross-MVP Traction Score comparison | No |
| `/retro` | Run retrospective, file feedback as GitHub issue | No |
| `/review` | Automated review-fix loop *(maintainers only)* | Yes |
| `/audit` | Analyze template structural quality | No |
| `/solve` | First-principles analysis for complex decisions | No |

**Utility**

| Skill | What it does | Waits for approval? |
|-------|-------------|---------------------|
| `/optimize-prompt` | Optimize a prompt using Claude best practices | No |
| `/upgrade` | Merge upstream template changes, reconcile memory | Yes |

## Supported stacks

| Category | Options | Default |
|----------|---------|---------|
| Framework | nextjs, hono, commander, virtuals-acp | nextjs |
| Hosting | vercel, railway | vercel |
| Database | supabase, sqlite | supabase |
| Auth | supabase | supabase |
| UI | shadcn | shadcn |
| Analytics | posthog | posthog |
| Testing | playwright, vitest | — |
| Payment | stripe | — |
| Distribution | google-ads, meta-ads, reddit, reddit-organic, twitter, twitter-organic, email-campaign | — |
| Email | resend | — |
| AI | anthropic | — |
| Images | fal | — |
| External | retell-ai, twilio | — |
| Surface | co-located, detached, none | — |

Override any default in `experiment.yaml` under `stack`. To add a new technology, create a stack file at `.claude/stacks/<category>/<name>.md`.

## Agents

Every `/verify` triggers up to 10 specialized agents in parallel:

**Quality** — design-critic, ux-journeyer, performance-reporter, accessibility-scanner
**Security** — security-defender, security-attacker, security-fixer
**Spec** — spec-reviewer, behavior-verifier
**Build** — build-info-collector, observer

`/bootstrap` adds 8 scaffold agents (setup, init, libs, pages, externals, images, landing, wire) that build the app concurrently. Additional agents handle gate-keeping, pattern classification, design consistency, provisioning scans, and visual/task implementation. 25 agents total across the system.

## Project structure

```
.claude/
  commands/          # 16 slash command definitions (state machine dispatchers)
  agents/            # 25 agent specifications
  procedures/        # 23 agent behavior contracts
  stacks/            # 29 pluggable stack files (14 categories)
  archetypes/        # 3 product archetypes (web-app, service, cli)
  patterns/          # 147 state files + shared patterns (verify, security, TDD, design)
  hooks/             # 14 enforcement hooks (state gates, commit guards, merge checks)
experiment/
  experiment.yaml    # Single source of truth for what to build
  experiment.example.yaml  # QuickBill reference example
  EVENTS.yaml        # Canonical event definitions for analytics
scripts/
  validators/        # Modular CI validators (analytics, stack deps, prose sync)
  validate-*.py      # experiment.yaml and frontmatter validation
  consistency-check.sh  # Cross-file consistency verification
  q-score.py         # Quality score computation
docs/                # Prerequisites, troubleshooting, technical reference
.runs/               # Skill execution artifacts, agent traces, context files
```

## Common issues

1. **`make validate` fails with TODOs** — open experiment.yaml and replace every `TODO`
2. **`/bootstrap` fails** — run `gh auth login` to authenticate GitHub CLI
3. **`/verify` fails** — make sure Docker Desktop is running (for supabase projects)
4. **Build fails** — check that `.env.local` has all variables from `.env.example`
5. **`/deploy` fails** — run `vercel login` and `npx supabase login` first
6. **Deployment broken?** — run `/rollback` for instant recovery to the previous deployment

For more issues, see [docs/troubleshooting.md](docs/troubleshooting.md).

## Documentation

- [docs/prerequisites.md](docs/prerequisites.md) — Full setup instructions
- [docs/troubleshooting.md](docs/troubleshooting.md) — All known issues
- [docs/technical-reference.md](docs/technical-reference.md) — Project structure, migrations, stack and archetype reference
- [.claude/procedures/google-ads-setup.md](.claude/procedures/google-ads-setup.md) — Google Ads setup for `/distribute`
- [docs/CONVENTIONS.md](docs/CONVENTIONS.md) — Implementation patterns established during bootstrap

## Contributing

All changes go through pull requests — never commit directly to `main`. CI runs validation on every PR. See [CLAUDE.md](CLAUDE.md) for the full rule set.

## License

MIT
