# STATE 2: VALIDATE_ANALYTICS

**PRECONDITIONS:**
- Prerequisites validated (STATE 1 POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: client + server analytics paths | service/cli: server analytics only (no client file)

1. **project_name source match:**
   - Read `name` from experiment.yaml
   - Grep analytics files for `PROJECT_NAME` constant: always check `src/lib/analytics-server.ts`; check `src/lib/analytics.ts` only when it exists (web-app only — service/cli have no client analytics file)
   - Check if the constant value matches the experiment.yaml name
   - If match: write `project_name_verified: true, project_name_mismatch: false`
   - If mismatch or "TODO": write `project_name_verified: true, project_name_mismatch: true` — do NOT stop, State 3 will fix it
   - Check command:
     ```bash
     EXPECTED=$(python3 -c "import yaml; print(yaml.safe_load(open('experiment/experiment.yaml')).get('name', ''))")
     if [ ! -f src/lib/analytics-server.ts ]; then
       echo "STOP: Analytics library files not found. Run /bootstrap first to scaffold analytics support, then re-run /distribute."
       exit 1
     fi
     MATCH=true
     if [ -f src/lib/analytics.ts ]; then
       grep -q "PROJECT_NAME = \"$EXPECTED\"" src/lib/analytics.ts 2>/dev/null || MATCH=false
     fi
     grep -q "PROJECT_NAME = \"$EXPECTED\"" src/lib/analytics-server.ts 2>/dev/null || MATCH=false
     $MATCH
     ```

2. **Static placeholder check (archetype-aware, env-first, pre-flight):**
   - Read `type` from experiment.yaml (default: `web-app` if missing or unparseable).
   - **Env-first short-circuit:** read `NEXT_PUBLIC_POSTHOG_KEY` from `.env.local` (preferred) or the calling shell's environment. If set to a non-empty value other than `phc_TEAM_KEY`, log "Analytics env override detected — skipping placeholder grep" and continue to step 3. Source-level placeholder is irrelevant when env wins at runtime; greppping it would block the legitimate env-override workflow (where the user sets the key in Vercel/Railway and never replaces source). This mirrors the prebuild script's Path 1 logic in `analytics/posthog.md` `## Production Observability > Layer 1`.
   - Otherwise (no env override OR env still equals the placeholder), determine grep paths by archetype:
     - web-app: `src/lib/analytics.ts`, `src/lib/analytics-server.ts`, `src/lib/events.ts`
     - service: `src/lib/analytics-server.ts`, `src/app/route.ts`
     - cli: `src/lib/analytics-server.ts`, `site/index.html`
   - Grep each existing path for the literal `phc_TEAM_KEY` (single OR double-quoted).
   - If any file contains the placeholder AND no env override is set: STOP with an actionable error listing the files. This catches the same misconfiguration class as the analytics stack file's `## Production Observability` Layer 1 (build-time) and Layer 2 (runtime), as the third gate before paid distribution begins.
   - Check command:
     ```bash
     ARCHETYPE=$(python3 -c "
     import yaml
     try:
         d = yaml.safe_load(open('experiment/experiment.yaml'))
         print(d.get('type', 'web-app'))
     except Exception:
         print('web-app')
     ")
     # Env-first short-circuit: respect NEXT_PUBLIC_POSTHOG_KEY override the same
     # way the prebuild script does. Read .env.local first, then fall back to the
     # calling shell. Strip surrounding quotes the way dotenv-style parsers do.
     KEY_VAL=""
     if [ -f .env.local ]; then
       KEY_VAL=$(grep -E '^[[:space:]]*NEXT_PUBLIC_POSTHOG_KEY[[:space:]]*=' .env.local \
         | head -1 | sed -E 's/^[^=]+=[[:space:]]*//' | sed -E 's/^"(.*)"$/\1/' | sed -E "s/^'(.*)'\$/\1/")
     fi
     [ -z "$KEY_VAL" ] && KEY_VAL="${NEXT_PUBLIC_POSTHOG_KEY:-}"
     if [ -n "$KEY_VAL" ] && [ "$KEY_VAL" != "phc_TEAM_KEY" ]; then
       echo "Analytics env override detected (NEXT_PUBLIC_POSTHOG_KEY) — skipping placeholder grep"
     else
       ANALYTICS_FILES="src/lib/analytics-server.ts"
       case "$ARCHETYPE" in
         web-app) ANALYTICS_FILES="$ANALYTICS_FILES src/lib/analytics.ts src/lib/events.ts" ;;
         service) ANALYTICS_FILES="$ANALYTICS_FILES src/app/route.ts" ;;
         cli)     ANALYTICS_FILES="$ANALYTICS_FILES site/index.html" ;;
       esac
       PLACEHOLDER_FILES=()
       for f in $ANALYTICS_FILES; do
         [ -f "$f" ] || continue
         if grep -q '"phc_TEAM_KEY"\|'"'"'phc_TEAM_KEY'"'"'' "$f"; then
           PLACEHOLDER_FILES+=("$f")
         fi
       done
       if [ ${#PLACEHOLDER_FILES[@]} -gt 0 ]; then
         echo "STOP: PostHog is not configured for distribution. The placeholder 'phc_TEAM_KEY' is still present in:"
         printf '  - %s\n' "${PLACEHOLDER_FILES[@]}"
         echo "Replace the placeholder with your team's PostHog key (or set NEXT_PUBLIC_POSTHOG_KEY in .env.local for the env-override workflow), redeploy, then re-run /distribute."
         exit 1
       fi
     fi
     ```
   - This step does NOT alter the existing `analytics_live` precondition — that is set by Step 3 below. It runs first because grepping local source is faster and more reliable than HogQL queries (which can fall back to manual when `query:read` scope is missing).

3. **Live analytics verification:**
   - Read `name` from experiment.yaml and `deployed_at` from `.runs/deploy-manifest.json`
   - Read `stack.analytics` value from experiment.yaml and read the analytics stack file at `.claude/stacks/analytics/<value>.md`
   - Find the **Auto Query** section — follow its instructions to verify live events
   - Read `experiment/EVENTS.yaml` and collect all event names where `funnel_stage` is `reach` (e.g., `visit_landing` for web-app, `api_call` for service, `command_run` for CLI)
   - Query for ANY of these reach-stage events filtered by `project_name = '<name>'` since `<deployed_at>`
   - If count > 0 for any reach event: log "Analytics verified: reach events found ([event names])" and write `analytics_live: true`
   - If count = 0 for all reach events, run a secondary diagnostic query for ALL events matching the project name since deployment
   - If the secondary query returns other events but no reach-stage events: stop "Analytics is receiving events from your app, but no reach-stage events (visit_landing, api_call, command_run) from the surface. The surface page analytics may be broken. Check the landing page/root handler code for missing tracking imports."
   - If the secondary query also returns 0 events: stop "No analytics events found for project '<name>' since deployment. Open <deployed_url> in your browser, wait 60 seconds, then re-run `/distribute`."
   - If the analytics stack file has no Auto Query section, skip live verification and log: "Live analytics verification skipped — provider does not support auto-query. Verify manually that events are flowing." Write `analytics_live: true`.

4. **Load hypothesis:**
   - If `.runs/spec-manifest.json` exists, read it and extract all hypotheses where `category` is `"demand"` or `"reach"` (the categories relevant to distribution). For each: `statement`, `metric.formula`, `metric.threshold`.
   - Store as hypothesis context for State 4 GENERATE. If the file does not exist, skip — all subsequent states work without it.
   - Write `hypothesis_loaded: true/false` to preconditions

5. **PageSpeed check:**
   - Read the deployed URL from preconditions
   - Query PageSpeed Insights API:
        ```bash
        SCORE=$(curl --max-time 30 -s "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=$DEPLOYED_URL&strategy=mobile&category=performance" | python3 -c "
        import json, sys
        data = json.load(sys.stdin)
        score = data.get('lighthouseResult', {}).get('categories', {}).get('performance', {}).get('score', 0)
        print(int(score * 100))
        ")
        echo "PageSpeed mobile score: $SCORE"
        ```
   - If score >= 70: log "PageSpeed mobile: [score]/100 (meets Phase 1 threshold)"
   - If score < 70: WARN (non-blocking): "PageSpeed mobile: [score]/100 (below Phase 1 threshold of 70). Ads may underperform with slow landing pages. Consider running `/change improve landing page performance` before enabling the campaign."
   - If curl fails (network error, timeout): WARN (non-blocking): "PageSpeed check failed (network error). Verify manually at https://pagespeed.web.dev/"
   - This is a WARNING, not a blocker — the skill continues regardless of the score.
   - Write `pagespeed_score` to preconditions (integer score, or `null` if failed)

**POSTCONDITIONS:**
- project_name check completed (verified or mismatch recorded)
- Live analytics verification passed
- Hypothesis loaded or skipped
- PageSpeed checked or failed with warning
- `.runs/distribute-preconditions.json` updated with: `project_name_verified`, `project_name_mismatch`, `analytics_live`, `hypothesis_loaded`, `pagespeed_score`

Update the preconditions artifact:
```bash
PAYLOAD=$(python3 -c "
import json
p = json.load(open('.runs/distribute-preconditions.json'))
p['project_name_verified'] = True  # or False
p['project_name_mismatch'] = False  # or True
p['analytics_live'] = True
p['hypothesis_loaded'] = True  # or False
p['pagespeed_score'] = None  # or integer
print(json.dumps(p))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/distribute-preconditions.json \
  --payload "$PAYLOAD" \
  --skill distribute
```

**VERIFY:**
```bash
python3 -c "import json; p=json.load(open('.runs/distribute-preconditions.json')); assert p.get('project_name_verified') is not None; assert p.get('analytics_live')"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh distribute 2
```

**NEXT:** Read [state-3-implement.md](state-3-implement.md) to continue.
