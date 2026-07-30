# STATE 0: READ_CONTEXT

**PRECONDITIONS:**
- Git repository exists in working directory

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: count page directories | service: count API routes | cli: count command modules; +surface pages if detached

Verify `experiment/experiment.yaml` exists. If not, stop and tell the user: "No experiment found -- `experiment/experiment.yaml` is missing. Make sure you're in the right project directory."

Verify `experiment/EVENTS.yaml` exists. If not, stop and tell the user: "experiment/EVENTS.yaml not found. This file defines all analytics events and is required. Restore it from your template repo or re-create it following the format in the experiment/EVENTS.yaml section of the template."

If `package.json` does not exist, warn: "No app found -- this retro will be based on your qualitative feedback only. If you want to include analytics data, run `/bootstrap` and `/deploy` first."

If `.runs/iterate-manifest.json` exists, read it and extract the `verdict`, `bottleneck`, and `recommendations` fields. Include in the summary: "Last `/iterate` analysis: verdict **[verdict]**, bottleneck: [bottleneck.diagnosis]." This context will inform Q1 follow-up.

If `.runs/verify-history.jsonl` exists, read it and compute per-skill Q summary:
```bash
python3 -c "
import json
entries = [json.loads(l) for l in open('.runs/verify-history.jsonl') if l.strip()]
if not entries:
    print('No Q-score data available.')
else:
    from collections import defaultdict
    groups = defaultdict(list)
    for e in entries:
        groups[e.get('skill','unknown')].append(e.get('q_skill', None))
    print('Skill Quality Summary:')
    for skill, qs in sorted(groups.items()):
        qs = [q for q in qs if q is not None]
        if qs:
            print(f'  {skill}: {len(qs)} runs, avg Q={sum(qs)/len(qs):.2f}, min Q={min(qs):.2f}')
" 2>/dev/null || echo "No Q-score history found."
```
Include the output in the summary presented to the user.

Collect these data points and present a summary before asking questions:

1. **Git activity**
   - Run `git log --oneline --no-decorate -50` -- report commit count and date range
   - Run `gh pr list --state all --limit 50` -- report PR counts (merged, open, closed)

2. **App scope**
   - Count primary units based on archetype (read `.claude/archetypes/<type>.md`, type from experiment.yaml, default `web-app`):
     - web-app: count page directories in `src/app/` (excluding `api/`)
     - service: count API route directories (e.g., `src/app/api/` or `src/routes/`)
     - cli: count command modules in `src/commands/`
   - If the archetype has a detached surface (`stack.surface: detached` or inferred), also count surface pages (e.g., `site/` directory or deployed surface assets)
   - Count production dependencies from `package.json` (if it exists)

3. **Spec files**
   - Read `experiment/experiment.yaml` -- extract experiment name, description, target user, thesis, funnel thresholds
   - Read `experiment/EVENTS.yaml` -- list events being tracked

Present the summary and then proceed to STATE 1.

**POSTCONDITIONS:**
- `experiment/experiment.yaml` has been read <!-- enforced by agent behavior, not VERIFY gate -->
- `experiment/EVENTS.yaml` has been read <!-- enforced by agent behavior, not VERIFY gate -->
- Git activity and app scope data collected <!-- enforced by agent behavior, not VERIFY gate -->
- Iterate manifest and Q-score history read (if available) <!-- enforced by agent behavior, not VERIFY gate -->
- Summary presented to user <!-- enforced by agent behavior, not VERIFY gate -->
- `.runs/retro-context.json` exists

**VERIFY:**
```bash
test -f .runs/retro-context.json
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh retro 0
```

**NEXT:** Read [state-1-interview.md](state-1-interview.md) to continue.
