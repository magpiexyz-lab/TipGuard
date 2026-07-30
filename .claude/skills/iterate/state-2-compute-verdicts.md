# STATE 2: COMPUTE_VERDICTS

**PRECONDITIONS:**
- Funnel data gathered (STATE 1 POSTCONDITIONS met)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: visit/CTA/signup/payment/return funnel labels | service: API call/auth/first-call/paid/retention | cli: install/run/first-success/paid/retention

### Per-Hypothesis Verdicts (if spec-manifest.json exists)

Read `.runs/spec-manifest.json`. If the file does not exist, skip this subsection entirely (backward compatible -- experiments created before /spec won't have it).

For each hypothesis in `spec-manifest.json` where `status` is `"testing"` (not `"resolved"`):

1. **Dependency check**: if the hypothesis has `depends_on[]`, check whether any parent hypothesis has verdict `REJECTED`. If so, set this hypothesis's verdict to `BLOCKED` and skip metric comparison.
2. **Compute metric**: parse `metric.formula` (e.g., `"signup_complete / visit_landing"`), compute the value from event counts gathered in STATE 1, then compare the result against `metric.threshold` using `metric.operator` (`gte`, `lte`, `gt`, `lt`, `eq`)
3. **Compare**: computed value vs `metric.threshold` using `metric.operator`
4. **Verdict**:
   - `CONFIRMED` -- computed value satisfies `metric.operator` against `metric.threshold`
   - `REJECTED` -- computed value does NOT satisfy `metric.operator` against `metric.threshold` AND sample size >= 30
   - `INCONCLUSIVE` -- sample size < 30
   - `BLOCKED` -- a parent in `depends_on[]` was REJECTED
5. **Confidence tag** based on sample size:
   - <30: "insufficient data"
   - 30-100: "directional signal"
   - 100-500: "reliable"
   - 500+: "high confidence"

Output:
```
Hypothesis Verdicts
-------------------
  [CATEGORY]   [formula] = [computed] vs [metric.threshold] ([metric.operator])   [PASS / FAIL / ? INCONCLUSIVE / BLOCKED (parent: h-XX)]  ([confidence] -- [N] [unit])
  ...
```

If ALL testable hypotheses are CONFIRMED (excluding BLOCKED) and verdict from the overall assessment is SCALE, note:
> All hypotheses confirmed. This experiment has validated its core assumptions. Consider scaling with `/change`.

### Validation Scorecard

Map funnel metrics to validation dimensions. Score each 0-100 as `(actual / threshold) * 100`, capped at 100.

| Dimension | Metric | Actual | Threshold | Score | Confidence | Available |
|-----------|--------|--------|-----------|-------|------------|-----------|
| REACH | ad CTR + visit count | [value] | [threshold] | [0-100] | [tag] | L1+ |
| DEMAND | CTA click rate + signup rate | [value] | [threshold] | [0-100] | [tag] | L1+ |
| ACTIVATE | activation rate + time-to-value | [value] | [threshold] | [0-100] | [tag] | L2+ |
| MONETIZE | pricing interaction + payment | [value] | [threshold] | [0-100] | [tag] | L2+ |
| RETAIN | return visits + repeat behavior | [value] | [threshold] | [0-100] | [tag] | L3+ |

- If experiment level < dimension level, show "--" for that row with "(not tested at this level)"
- Confidence per-dimension is based on sample size (same tags as hypothesis verdicts)
- Threshold sourcing (in priority order): (1) highest-priority hypothesis per dimension's `metric.threshold` from spec-manifest.json (hypotheses are mapped to dimensions by category), (2) experiment/EVENTS.yaml funnel benchmarks as fallback. Funnel dimensions in experiment.yaml carry only `available_from` -- dimension thresholds are derived from hypotheses, not from the funnel config directly.

#### Descriptive funnel labels by archetype

Use these human-readable labels in the Scorecard output by archetype:

| Archetype | REACH | DEMAND | ACTIVATE | MONETIZE | RETAIN |
|-----------|-------|--------|----------|----------|--------|
| web-app | Landing page visits | CTA clicks / signups | First core action | Payment starts | Return visits |
| service | API adoption rate | Integration requests | First successful API call | API key upgrades | Monthly active integrations |
| cli | Install rate | Daily active usage | First successful command | Pro feature adoption | Update rate |

#### Decision Framework Reference

The `decision_framework` field in experiment.yaml `funnel` section is human-readable documentation of the experiment's decision criteria. The actual verdict logic uses the two-tier approach: pace-based overall verdict (STATE 3) + per-dimension Scorecard ratios (this state). The `decision_framework` field serves as operator context -- display it in the STATE 4 summary for reference but do not use it to override the algorithmic verdict.

### Bottleneck

Identify the dimension with the lowest `actual / threshold` ratio (excluding dimensions not available at the current level):

```
Bottleneck: [DIMENSION] (ratio [N.NN]) -- [dimension-specific recommendation]
```

Dimension-specific recommendations:
- **REACH** -> improve ad targeting, headline, or channel selection
- **DEMAND** -> improve CTA clarity, value proposition, or signup friction
- **ACTIVATE** -> improve onboarding, reduce steps to first value, simplify core action
- **MONETIZE** -> adjust pricing, add value justification, or feature comparison
- **RETAIN** -> improve onboarding, engagement hooks, or usage feedback

### Ads Performance (if ads.yaml exists)

If `experiment/ads.yaml` exists and the user provided ads data in STATE 1, include this table:

```
## Ads Performance

| Metric | Actual | Threshold | Status |
|--------|--------|-----------|--------|
| CTR | [%] | >1% | [status] |
| CPC | [$] | <$[max_cpc from ads.yaml guardrails.max_cpc_cents / 100] | [status] |
| Spend | [$] | /$[total_budget from ads.yaml budget.total_budget_cents / 100] | [status] |
| Paid activations | [N] | >=[thresholds.expected_activations from ads.yaml] | [status] |
```

Read `experiment/ads.yaml` to populate threshold values. Use the user-provided ads data for actual values.

### Variant Winner Analysis (if experiment.yaml has `variants`)

If the user provided per-variant metrics in STATE 1, present a comparison:

```
## Variant Comparison

| Variant | Visits | Signups | Activations | Visit->Signup | Signup->Activate |
|---------|--------|---------|-------------|---------------|------------------|
| [slug]  | [N]    | [N]     | [N]         | [%]           | [%]              |
| [slug]  | [N]    | [N]     | [N]         | [%]           | [%]              |

**Winner:** [slug] -- [reason]
**Confidence:** [Clear (2x+ difference and 50+ visits per variant) | Likely (1.5x+ and 30+ visits) | Too early (<30 visits per variant -- extend the test)]
```

- **Clear winner (2x+ conversion rate, 50+ visits per variant)**: recommend consolidating on the winning variant -- remove the losing variant, update root `/` to the winner's messaging
- **Likely winner (1.5x+, 30+ visits)**: recommend extending the test for more data, or consolidating if time is short
- **Too early (<30 visits per variant)**: recommend extending the test duration or increasing traffic -- no reliable signal yet
- **No winner (similar conversion rates)**: recommend testing a new messaging angle -- current variants may not differentiate enough

**POSTCONDITIONS:**
- Per-hypothesis verdicts computed (if spec-manifest.json exists)
- Validation Scorecard computed with per-dimension scores
- Bottleneck identified
- Variant analysis completed (if applicable)
- Ads performance assessed (if applicable)

- **Write verdicts artifact** (`.runs/iterate-verdicts.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  verdicts = {
      'dimension_scores': {},
      'bottleneck': '<dimension>',
      'hypothesis_verdicts': []
  }
  print(json.dumps(verdicts))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/iterate-verdicts.json \
    --payload "$PAYLOAD" \
    --skill iterate
  ```

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/iterate-verdicts.json')); assert isinstance(d.get('dimension_scores'), dict) and len(d['dimension_scores'])>0, 'dimension_scores empty'; assert d.get('bottleneck'), 'bottleneck empty'; assert isinstance(d.get('hypothesis_verdicts'), list), 'hypothesis_verdicts not a list'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate 2
```

**NEXT:** Read [state-3-decision.md](state-3-decision.md) to continue.
