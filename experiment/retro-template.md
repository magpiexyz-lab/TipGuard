# Retrospective Template

This template guides a structured retrospective at the end of an experiment.
To run a retro: open Claude Code and run `/retro`.

## Part 1: Automated Data (Claude gathers this)

Claude runs these commands and presents a summary:
- `git log --oneline --no-decorate` (last 50 commits) — commit count and date range
- `gh pr list --state all --limit 50` — PR counts (merged, open, closed)
- Count pages in `src/app/` (excluding `api/`)
- Count production dependencies from `package.json`
- Read `idea/experiment.yaml` — experiment name, title, target user, thesis
- Read `experiment/EVENTS.yaml` — events being tracked

## Part 2: Four Questions (Claude asks these one at a time)

### Q1: Outcome
"What was the outcome of this experiment?"
- Succeeded — thesis validated (funnel thresholds met or exceeded)
- Partially succeeded — made progress but didn't fully validate the thesis
- Failed — thesis invalidated
- Inconclusive — not enough data or time

Follow-up: "What was the actual result vs your thesis?"

### Q2: What worked
"What worked well? (workflow, tools, stack, anything)"

### Q3: What was painful
"What was painful, confusing, or slow?"

### Q4: What was missing
"What capability did you wish you had but didn't?"

## Part 3: Output Format

Claude generates a structured document with these sections:
1. **Experiment Summary** — name, problem, solution, target user, outcome, metric results
2. **Timeline & Activity** — commits, PRs, pages built, scope delivered
3. **Stack Used** — from experiment.yaml
4. **Team Assessment** — answers to Q2-Q4
5. **Template Improvement Suggestions** — specific, actionable changes mapped to template components

## Part 4: File as GitHub Issue

After generating the retro, Claude files it as a GitHub Issue:
Set the template repo:
```
TEMPLATE_REPO="magpiexyz-lab/mvp-template"
```

Command Claude runs:
```
gh issue create \
  --repo $TEMPLATE_REPO \
  --title "Retro: <experiment-name> — <outcome>" \
  --label "retro" \
  --body "<structured retro content>"
```

The issue uses the retro issue template if one exists on the target repo.
