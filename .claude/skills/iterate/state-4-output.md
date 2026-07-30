# STATE 4: OUTPUT

**PRECONDITIONS:**
- Decision and recommendations complete (STATE 3 POSTCONDITIONS met)

**ACTIONS:**

### Save analysis for /change context

Write `.runs/iterate-manifest.json`:
```json
{
  "experiment_id": "<experiment.yaml name>",
  "round": 1,
  "verdict": "<SCALE|KILL|PIVOT|REFINE|TOO_EARLY>",
  "bottleneck": {
    "stage": "<funnel stage name>",
    "conversion": "<percentage>",
    "diagnosis": "<one-line diagnosis>",
    "dimension": "<REACH|DEMAND|ACTIVATE|MONETIZE|RETAIN>",
    "ratio": 0.65,
    "recommendation": "<dimension-specific recommendation>"
  },
  "recommendations": [
    {
      "action": "<what to do>",
      "skill": "</change ...>",
      "expected_impact": "<which metric improves>"
    }
  ],
  "variant_winner": "<slug or null>",
  "analyzed_at": "<ISO 8601>",
  "hypothesis_verdicts": [
    {
      "hypothesis_id": "<id from spec-manifest>",
      "metric_formula": "<metric.formula from hypothesis>",
      "metric_operator": "<metric.operator from hypothesis>",
      "computed_value": "<result of evaluating formula against event counts>",
      "threshold": "<metric.threshold from hypothesis>",
      "verdict": "<CONFIRMED|REJECTED|INCONCLUSIVE|BLOCKED>",
      "blocked_by": "<parent hypothesis id or null>",
      "sample_size": 0,
      "confidence_level": "<insufficient data|directional signal|reliable|high confidence>"
    }
  ],
  "funnel_scores": {
    "reach": { "score": 0, "confidence": "<tag>", "sample_size": 0, "threshold_source": "<hypothesis|events-yaml>" },
    "demand": { "score": 0, "confidence": "<tag>", "sample_size": 0, "threshold_source": "<hypothesis|events-yaml>" },
    "activate": { "score": 0, "confidence": "<tag>", "sample_size": 0, "threshold_source": "<hypothesis|events-yaml>" },
    "monetize": { "score": 0, "confidence": "<tag>", "sample_size": 0, "threshold_source": "<hypothesis|events-yaml>" },
    "retain": null
  }
}
```

- `experiment_id`: populated from experiment.yaml `name` field. Identifies which experiment this analysis belongs to.
- `round`: auto-incremented iteration counter. On first `/iterate` run, set to `1`. On subsequent runs, read existing `.runs/iterate-manifest.json` and set `round` to previous value + 1. This tracks how many iteration cycles the experiment has gone through.
- `hypothesis_verdicts` and `funnel_scores` are only populated when spec-manifest.json exists. Omit both fields for experiments without /spec.
- `bottleneck.dimension`, `bottleneck.ratio`, and `bottleneck.recommendation` are populated from the Validation Scorecard. For experiments without spec-manifest, populate from funnel analysis only (`dimension` and `ratio` may be null).

This file is read by `/change` to provide context for the next iteration.

### Q-score

Compute iterate analysis quality (see `.claude/patterns/skill-scoring.md`):

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.

```bash
RUN_ID=$(python3 -c "import json; print(json.load(open('.runs/iterate-context.json')).get('run_id', ''))" 2>/dev/null || echo "")
ITERATE_DIMS=$(python3 -c "
import json
try:
    m = json.load(open('.runs/iterate-manifest.json'))
    verdict = m.get('verdict', 'TOO_EARLY')
    q_verdict = 1.0 if verdict != 'TOO_EARLY' else 0.5
    hvs = m.get('hypothesis_verdicts', [])
    has_data = any(h.get('sample_size', 0) > 0 for h in hvs) if hvs else False
    q_data = 1.0 if has_data else 0.5
    print(json.dumps({'data': q_data, 'verdict': q_verdict}))
except:
    print(json.dumps({'completion': 1.0}))
" 2>/dev/null || echo '{"completion": 1.0}')
PAYLOAD=$(ITERATE_DIMS_ENV="$ITERATE_DIMS" python3 -c "
import json, os
print(json.dumps({
    'scope': 'iterate',
    'dims': json.loads(os.environ['ITERATE_DIMS_ENV'])
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/q-dimensions.json \
  --payload "$PAYLOAD" \
  --skill iterate || true
```

### Summarize next steps

End with a clear, numbered action list. Prepend the verdict from STATE 3:

```
## Recommended Next Steps

**Verdict: [SCALE/KILL/PIVOT/REFINE/TOO EARLY]** -- [one-line summary]

1. Run `/change sharpen landing page headline to address [specific user pain]`
2. Run `/change add onboarding checklist after signup`
3. Post in [distribution channel from experiment.yaml] -- drive more top-of-funnel traffic

Your measurement window ends in [X days]. [Verdict-specific guidance].
```

### Retro reminder
If the experiment is near its planned end date or the user is considering stopping:
> Your measurement window ends in [X days]. When you're ready to wrap up, run **`/retro`** to generate a structured retrospective and file it as feedback on the template repo.

### Next Check-in

Based on the measurement window and current progress, provide a concrete schedule:

```
## Next Check-in

| Milestone | Date | Action |
|-----------|------|--------|
| Next data check | [3 days from now] | Run `/iterate` again |
| Decision point | [when time_pct hits 50%] | Verdict becomes actionable -- REFINE/KILL verdicts require decision |
| Window closes | [experiment end date] | Run `/retro` to file retrospective |
```

- Calculate dates from the experiment timeline and the elapsed days reported in STATE 3
- If verdict is TOO EARLY: check deployment and traffic state to provide actionable next steps:
  - If `.runs/deploy-manifest.json` does not exist:
    - If archetype is `web-app` or `service`: "Your app isn't deployed yet. Run `/deploy` to go live, then return to `/iterate` after a few days of traffic."
    - If archetype is `cli` with `surface: detached`: "Your CLI surface isn't deployed yet. Run `/deploy` for the marketing surface, then `npm publish` to publish the CLI package."
    - If archetype is `cli` with `surface: none`: "Your CLI hasn't been published yet. Run `npm publish` or create a GitHub Release, then collect usage data before re-running `/iterate`."
  - If deployed but analytics shows 0 events: "Your app is deployed but receiving no traffic. Run `/distribute` to drive traffic, or manually visit the app to verify it's accessible."
  - If deployed and some events exist: "Traffic is building -- check back in 3 days or when 30+ visits are logged, whichever comes first."
- If verdict is KILL, the next check-in is NOW -- recommend immediate decision
- Tell the user: "Set a calendar reminder for [next check-in date] to run `/iterate` again."

**POSTCONDITIONS:**
- `.runs/iterate-manifest.json` written with verdict, bottleneck, recommendations, and scores
- Next steps summary presented to user
- Next check-in schedule provided

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/iterate-manifest.json')); assert d.get('experiment_id'), 'experiment_id empty'; assert isinstance(d.get('round'), int) and d['round']>=1, 'round invalid'; assert d.get('verdict') in ('SCALE','KILL','PIVOT','REFINE','TOO_EARLY'), 'verdict=%s' % d.get('verdict'); assert d.get('analyzed_at'), 'analyzed_at empty'; assert isinstance(d.get('recommendations'), list), 'recommendations not a list'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate 4
```

**NEXT:** Skill states complete.
