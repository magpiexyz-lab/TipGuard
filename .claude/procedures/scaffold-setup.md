# Scaffold: Project Setup

## Prerequisites
- Branch already created (by bootstrap Step 0)
- Plan approved and saved to `.runs/current-plan.md`
- Read all context files listed in your task assignment before starting

## Steps

### Step 1: Package installation and framework setup
- Create `package.json` with `name` from experiment.yaml and project setup from the framework stack file (.nvmrc, scripts, engines, tsconfig, config)
- Install packages from all stack files whose categories are present in experiment.yaml `stack`
- Install dev dependencies from the framework and UI stack files
- The lead has already checked `typescript-language-server` availability. The TSP status is provided in your prompt. If status is `"skipped"`, proceed without it. If status is `"available"`, LSP type-checking is active.
- Run the UI setup commands from the UI stack file
- After UI setup, verify the UI stack file's post-setup checks pass (PostCSS config, globals.css, scripts intact). If any post-setup check fails: stop and tell the user which check failed and how to fix it (e.g., "PostCSS config was overwritten by shadcn init — restore it from the framework stack file template"). Do not proceed until all post-setup checks pass.
- If any install command fails: stop, show the error, and ask the user to fix the environment issue. After fixing, tell Claude: "Continue the bootstrap on this branch from the install step." Claude will re-run the failed install and any subsequent install commands, then continue. Do NOT re-run `/bootstrap` (that would create a duplicate branch). If you close this conversation: either (1) commit partial files on this branch (`git add -A && git commit -m "WIP: partial install"`), then tell Claude "Continue the bootstrap on this branch from the install step"; or (2) switch to main (`git checkout main`), run `make clean`, and start `/bootstrap` fresh.

