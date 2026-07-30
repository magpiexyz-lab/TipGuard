# Prerequisites

Everything you need before running your first experiment. Ask a technical teammate for help if anything is unclear.

## Tools to install

Install these on your computer. Each item shows which project types need it.

| Tool | Why | Install | Verify | Needed for |
|------|-----|---------|--------|------------|
| [Python 3](https://www.python.org/) + PyYAML | Validates your experiment.yaml | [python.org](https://www.python.org/downloads/) then `pip3 install pyyaml` | `python3 --version` | All projects |
| [Node.js](https://nodejs.org/) 20+ | Runs the app and build tools | [nodejs.org](https://nodejs.org/) | `node --version` | All projects |
| [GitHub CLI](https://cli.github.com/) | Creates branches and pull requests | [cli.github.com](https://cli.github.com/) | `gh --version` then `gh auth login` | All projects |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Runs a local database for testing | [docker.com](https://www.docker.com/products/docker-desktop/) | Open Docker Desktop | web-app / service with `stack.database: supabase` |
| Vercel CLI | Deploys your app | `npm i -g vercel` then `vercel login` | `vercel --version` | web-app / service with `stack.hosting: vercel` |
| Supabase CLI | Manages database migrations | Used via `npx supabase` (no install) | `npx supabase --version` then `npx supabase login` | web-app / service with `stack.database: supabase` |

> **npm** comes bundled with Node.js. This template uses npm exclusively — do not use yarn or pnpm.

## Service accounts

Sign up for these services. Most have free tiers that are more than enough for experiments.

| Service | When needed | Sign up |
|---------|-------------|---------|
| [Claude Code](https://claude.ai/code) | Always (runs all skills) | [claude.ai/code](https://claude.ai/code) — requires a paid plan or API credits |
| [GitHub](https://github.com/) | Always (hosts your code) | [github.com](https://github.com/) |
| [PostHog](https://posthog.com/) | When `stack.analytics: posthog` | [posthog.com](https://posthog.com/) — one shared project for all experiments (free tier: 1M events/month) |
| [Vercel](https://vercel.com/) | When `stack.hosting: vercel` | [vercel.com](https://vercel.com/) — free tier covers most experiments |
| [Supabase](https://supabase.com/) | When `stack.database: supabase` or `stack.auth: supabase` | [supabase.com](https://supabase.com/) — free tier: 2 projects |
| [Stripe](https://stripe.com/) | When `stack.payment: stripe` | [stripe.com](https://stripe.com/) — use test mode for experiments |
| [Resend](https://resend.com/) | When `stack.email: resend` | [resend.com](https://resend.com/) — free tier: 100 emails/day |

> The defaults in experiment.yaml use Supabase, PostHog, and Vercel. If you change stack values, substitute the corresponding services.

## OAuth provider accounts (optional)

If your `experiment.yaml` declares `stack.auth_providers` (e.g., `[google, github, facebook]`), prepare developer accounts at these providers **before** running `/deploy`:

| Provider | Account needed | Sign up / access |
|----------|---------------|-----------------|
| Google | Google Cloud Project in your Workspace | [console.cloud.google.com](https://console.cloud.google.com/) — create a project if you don't have one |
| GitHub | Owner or Member access to your GitHub Organization | [github.com/organizations](https://github.com/organizations) — check with your Org admin |
| Facebook | Meta for Developers account | [developers.facebook.com](https://developers.facebook.com/) — sign up with your Facebook account |

> You do **not** need to create the OAuth Apps yet. The actual OAuth App creation (with redirect URIs) happens during `/deploy`, once the Supabase project exists and the callback URL is known. This step just ensures you have the right accounts and permissions.

## Verify your setup

After installing everything, run this from your project folder:

```bash
make validate
```

If it prints errors, fix them before continuing. The most common issue is a missing PyYAML — run `pip3 install pyyaml` to fix it.
