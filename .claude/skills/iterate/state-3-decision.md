<!-- archetype-gate-exempt: presents archetype-agnostic verdict framework with reference-only mentions of service/cli archetypes; does not branch on archetype. -->

# STATE 3: DECISION

**PRECONDITIONS:**
- Verdicts and scores computed (STATE 2 POSTCONDITIONS met)

**ACTIONS:**

### Calculate progress

From the data gathered in STATE 1, determine:
- **Time elapsed**: ask the user how many days the experiment has been running and the total planned duration. Calculate `time_pct = elapsed_days / total_days`.
- **Target progress**: extract the target from experiment.yaml `thesis` (e.g., "10+ will complete at least one paid invoice within 2 weeks" -> target = 10 paid invoices). Compare against the closest matching funnel metric. Calculate `target_pct = achieved / target_number`.
- **Pace**: `pace = target_pct / time_pct`. A pace of 1.0 means exactly on track; >1.0 means ahead; <1.0 means behind.
- **Budget progress (if ads running)**: if the user provided ads spend data, calculate `budget_pct = spent / total_budget`.

### Apply verdict framework

Present the verdict table and determination:

| Dimension | Value |
|-----------|-------|
| Time | Day [N] of [total] ([time_pct]% elapsed) |
| Target | [achieved] of [target] [metric] ([target_pct]% achieved) |
| Pace | [pace]x ([interpretation]) |
| Budget | $[spent] of $[total] ([budget_pct]%) -- only if ads running |

Then apply the decision tree:

| Condition | Verdict |
|-----------|---------|
| time_pct < 25% AND total visits < 30 | **TOO EARLY** -- not enough data for a verdict. Sub-cases: if not yet deployed, run `/deploy` first; if deployed but low traffic, focus on distribution channels (see experiment.yaml `distribution`); if recently deployed, allow more time. Check back in a few days. For pure API services or CLIs deployed outside `/deploy` (e.g., via `make deploy` or manual deployment): if `.runs/deploy-manifest.json` does not exist, create it manually using the schema below to enable `/distribute` and `/teardown`. |

> **Manual `.runs/deploy-manifest.json` schema** (when deployment happened outside `/deploy`):
> ```json
> {
>   "name": "<experiment.yaml name>",
>   "archetype": "<service|cli>",
>   "surface_type": "<none|detached|co-located>",
>   "canonical_url": "<API base URL or distribution URL>",
>   "deployed_at": "<ISO 8601 timestamp>",
>   "stripe": {"webhook_endpoint_url": "<url>"}
> }
> ```
> Include only the per-service keys that match your experiment.yaml `stack` so `/teardown` can clean each up. See `/deploy` STATE 0 (service with `surface: none` stop message) for the canonical example.
| pace >= 0.7 | **SCALE** -- on track. Continue and optimize conversion at the biggest bottleneck. |
| pace 0.4-0.7 AND time_pct < 60% | **REFINE** -- behind pace but recoverable. Focus on the biggest funnel bottleneck identified in STATE 2. |
| pace 0.2-0.4 AND time_pct > 50% | **PIVOT** -- there's signal, but the angle is wrong. Change messaging or target user. |
| pace < 0.2 AND time_pct > 50% | **KILL** -- unlikely to reach target. Consider stopping. |
| 0 activations AND time_pct > 30% | **KILL** -- zero demand signal. Stop spending, re-evaluate positioning. |

Output the verdict prominently:

> ### Verdict: [SCALE / KILL / PIVOT / REFINE / TOO EARLY]
>
> **[One-line reasoning]**

### Verdict caveats

- The verdict is a **guideline, not an order** -- the user makes the final call
- Qualitative signals (user feedback, feature requests) can override quantitative pace
- If `thesis` target is not cleanly numeric (e.g., "validate that freelancers will pay"), use the closest measurable proxy and note the approximation
- For experiments without ads (organic only), budget dimension is omitted

### Funnel Diagnosis

Analyze the data to find where the funnel breaks. Present a funnel visualization:

```
## Funnel Analysis

| Stage | Count | Conversion | Diagnosis |
|-------|-------|-----------|-----------|
| [1st funnel event] | [count] | -- | [diagnosis] |
| [2nd funnel event] | [count] | [%] | [specific diagnosis] |
| ... (one row per event from experiment/EVENTS.yaml events map, filtered by requires/archetypes) | ... | ... | ... |
| [monetize-stage events if stack.payment present] | ... | ... | ... |
| [retain_return] | [count] | -- | [retention diagnosis] |

If `stack.payment` is absent from experiment.yaml, omit the `pay_start` and `pay_success` rows from the funnel table.

> Note: `retain_return` is a retention metric, not a conversion step. Show it below the funnel or as a separate row -- it does not have a meaningful conversion rate relative to the row above it.

## Biggest Bottleneck
Activation (signup -> first value): 22% conversion
Users sign up but don't [complete the core action].
```

Focus on the **biggest drop-off** in the funnel. That's where effort has the highest leverage.

### Recommend actions

Based on the diagnosis, recommend 1-3 specific actions. For each:
- **What**: concrete description of the change
- **Why**: how it addresses the bottleneck
- **Skill to use**: which /command to run
- **Expected impact**: what metric should improve

Common patterns:

| Bottleneck | Typical Actions |
|-----------|----------------|
| Low visit -> signup | `/change improve landing page copy and CTA` |
| Low signup_start -> complete | `/change fix signup errors` or `/change reduce signup form friction` |
| Low activation | `/change simplify [first-value action]` |
| Low pay conversion | `/change improve pricing/payment UX` |
| Low retention | `/change add [engagement hook]` |
| Everything low | Reconsider `target_user` or `distribution` -- may be a positioning problem, not a product problem |

**Service/CLI bottleneck patterns:**

| Bottleneck | Typical Actions |
|-----------|----------------|
| Low API calls / command runs | Distribution problem -- how do users discover the service/CLI? |
| Low activation (calls exist but no first-value action) | `/change simplify [activation action]` or improve onboarding |
| Low retention | `/change add [engagement hook]` or improve core value delivery |
| Everything low | Reconsider `target_user` or distribution channel |

| One variant clearly wins | `/change` to consolidate -- remove losing variant, make winner the sole landing page |
| No variant winner | Extend test for more data, or `/change` to try a new messaging angle |
| Verdict is SCALE with strong metrics | Suggest `/change` for scaling features: "Your metrics indicate product-market fit. Consider adding scaling features." |
| Production incident | `/rollback` to revert deploy, then `/change fix <root cause>` |

Present recommendations in priority order (highest impact first).

### Ads Decision (if ads.yaml exists and a stop condition fired)

If `experiment/ads.yaml` exists but the user reported no ads data in STATE 1 (campaign not yet launched), skip this section and instead note: "Ads config generated but campaign not yet launched. Create the campaign in your distribution channel's platform using `experiment/ads.yaml`, then return to `/iterate` after a few days of data."

If `experiment/ads.yaml` exists and the campaign reached `budget.click_target` paid clicks, OR exhausted `budget.total_budget_cents`, OR ended at its End date, present a go/no-go decision:

If the End date was reached with clicks below `budget.click_target` and spend below `budget.total_budget_cents`, say that the calendar alone is not a verdict deadline. Recommend extending the End date by `(cap - spent) / daily_budget` days, or stopping consciously.

| Signal | Interpretation | Action |
|--------|---------------|--------|
| 3+ paid activations | Demand validated | Continue: increase budget or `/change` to improve conversion |
| 1-2 paid activations | Weak signal | Extend 3 days or improve landing page, then re-evaluate |
| 0 activations, >10 signups | Activation problem | `/change` to reduce activation friction |
| 0 activations, >50 clicks, <3 signups | Landing page problem | `/change` to improve landing page |
| 0 activations, <50 clicks, <1% CTR | Targeting problem | Revise targeting in ads.yaml, re-run `/distribute` |
| 0 activations, <50 clicks, >1% CTR | Budget/time problem | Extend budget or experiment duration |

Read `thresholds.go_signal` and `thresholds.no_go_signal` from `experiment/ads.yaml` and use them as the primary decision criteria. The table above provides additional diagnostic detail.

### Update the experiment plan (if needed)

If the diagnosis reveals a need to change direction:

#### Minor pivot (keep same target user, adjust behaviors)
- Propose the changes to the user and list the specific edits to experiment.yaml
- The user should edit experiment.yaml manually, then run `/change ...` to implement the changes (or `make clean` followed by `/bootstrap` to rebuild from scratch)

#### Pivot (verdict is PIVOT -- signal exists but wrong angle)
- Identify what IS working (which funnel stage converts well)
- Propose messaging or positioning changes that preserve what works
- The user should run `/change` to adjust copy/CTA/targeting, NOT rebuild from scratch

#### Stop (verdict is KILL)
- Present the case: "The Step 3 verdict is KILL. The data suggests [current approach] isn't working because [reason]."
- Recommend immediate actions:
  1. Stop spending on ads/distribution -- further traffic is unlikely to change the outcome
  2. Run `/retro` to file a retrospective while findings are fresh
  3. If you deployed the app (via `/deploy`), run `/teardown` to remove cloud infrastructure and stop ongoing costs. If you only bootstrapped without deploying, skip this step -- there's no cloud infrastructure to clean up
  4. If pivoting: edit experiment.yaml with a new thesis/target_user, then `make clean` and `/bootstrap` to start fresh (or in a new repo)
  5. If pivoting: start fresh with a new experiment.
- Do NOT update experiment.yaml automatically -- the user should decide whether to pivot or stop

#### On track (verdict is SCALE)
- Say so clearly: "The Step 3 verdict is SCALE. You're on track. [X] of [target from thesis] achieved with [Y days] remaining."
- Recommend: keep going, focus on distribution, or run `/change improve conversion` to improve conversion
- If the experiment shows strong, sustained traction: suggest scaling actions: "Production quality is active. Consider `/change` to add scaling features."

**POSTCONDITIONS:**
- Pace and progress calculated
- Overall verdict determined (SCALE/KILL/PIVOT/REFINE/TOO EARLY)
- Funnel analysis presented with bottleneck identified
- 1-3 specific action recommendations provided
- Direction change guidance provided (if applicable)
- Verdict saved to iterate-context.json

Save the verdict to context before VERIFY:
```bash
PAYLOAD=$(python3 -c "
import json
ctx = json.load(open('.runs/iterate-context.json'))
ctx['verdict'] = '<VERDICT>'  # Replace with actual verdict from analysis
print(json.dumps(ctx))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/iterate-context.json \
  --payload "$PAYLOAD" \
  --skill iterate
```

**VERIFY:**
```bash
python3 -c "import json; ctx=json.load(open('.runs/iterate-context.json')); assert ctx.get('verdict'), 'verdict missing from iterate-context.json'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate 3
```

**NEXT:** Read [state-4-output.md](state-4-output.md) to continue.
