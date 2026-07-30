# STATE 1: RESEARCH

**PRECONDITIONS:**
- Input parsed and confirmed (STATE 0 POSTCONDITIONS met)

**ACTIONS:**

## Step 2: Pre-flight Research

Conduct desk research across 4 dimensions. For each, produce a structured finding:

| Dimension | What to assess |
|-----------|---------------|
| **Market exists** | Is there an active market? Are people spending money or time on this problem today? |
| **Problem validated** | Have real users expressed this pain? (forums, reviews, social posts, surveys) |
| **Competitive landscape** | Who else solves this? What's their approach? Where are the gaps? |
| **ICP identified** | Can you name a specific, reachable person who has this problem? |

For each dimension, record:
- `hypothesis_id`: `research_<dimension>` (e.g., `research_market_exists`)
- `finding`: 1-2 sentence summary of what was found
- `sources`: list of source types checked (e.g., "Reddit threads", "G2 reviews", "App Store listings")
- `confidence`: `high` | `medium` | `low`
- `verdict`: `pass` | `caution` | `fail`

Use web search to gather real data. If web search is unavailable, use your training knowledge and mark confidence as `low`.

### Display results

```
Pre-flight Research                                    N/4 passed
------------------------------------------------------------------
[pass/caution/fail] Market exists       [finding summary]        (confidence: high/medium/low)
[pass/caution/fail] Problem validated   [finding summary]        (confidence: high/medium/low)
[pass/caution/fail] Competitive gaps    [finding summary]        (confidence: high/medium/low)
[pass/caution/fail] ICP identified      [finding summary]        (confidence: high/medium/low)
```

### Stop on critical failure
If 2+ dimensions are `fail`: stop and tell the user:
> **Pre-flight failed.** [N] of 4 research checks failed. This idea may need rethinking before investing in an experiment.
>
> [List failed dimensions with reasons]
>
> Options:
> 1. Revise your idea and re-run `/spec`
> 2. Say "override" to proceed anyway (research will be marked as low-confidence)

Wait for the user to revise, override, or abandon.

**POSTCONDITIONS:**
- 4 research dimensions assessed with findings, sources, confidence, and verdicts
- Results displayed to user
- If 2+ failures: user chose to revise, override, or abandon

- **Write research artifact** (`.runs/spec-research.json`):
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  research = {
      'dimensions': [
          {'name': 'market_exists', 'verdict': '<pass|caution|fail>', 'confidence': '<high|medium|low>'},
          {'name': 'problem_validated', 'verdict': '<pass|caution|fail>', 'confidence': '<high|medium|low>'},
          {'name': 'competitive_landscape', 'verdict': '<pass|caution|fail>', 'confidence': '<high|medium|low>'},
          {'name': 'icp_identified', 'verdict': '<pass|caution|fail>', 'confidence': '<high|medium|low>'}
      ],
      'passed_count': 0
  }
  print(json.dumps(research))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/spec-research.json \
    --payload "$PAYLOAD" \
    --skill spec
  ```

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/spec-research.json')); dims=d.get('dimensions',[]); assert isinstance(dims, list) and len(dims)==4, 'expected 4 dimensions, got %d' % len(dims); assert all(x.get('verdict') in ('pass','caution','fail') for x in dims), 'invalid verdict in dimensions'; assert all(x.get('confidence') in ('high','medium','low') for x in dims), 'invalid confidence in dimensions'; assert isinstance(d.get('passed_count'), int), 'passed_count not int'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh spec 1
```

**NEXT:** Read [state-2-hypotheses.md](state-2-hypotheses.md) to continue.
