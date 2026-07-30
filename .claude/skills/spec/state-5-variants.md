# STATE 5: VARIANTS

**PRECONDITIONS:**
- Golden path derived (STATE 4 POSTCONDITIONS met)

**ACTIONS:**

## Step 5: Generate Variants

Generate 3-5 offer variants. Each variant is a different messaging angle for the same product.

### Variant fields
```yaml
- slug: time-saver               # URL-safe, lowercase, hyphens
  headline: "..."                 # Max 10 words, benefit-focused
  subheadline: "..."              # Max 25 words, how-it-works
  cta: "..."                      # Action verb + outcome (e.g., "Start invoicing free")
  pain_points:                    # Exactly 3
    - "..."
    - "..."
    - "..."
  promise: "..."                  # What they get (1 sentence)
  proof: "..."                    # Why believe it (social proof, mechanism, guarantee)
  urgency: "..."                  # Why now (scarcity, timing, cost of delay)
```

### Rules
- Headlines must have >30% word difference between any two variants (no minor rewording)
- Each variant targets a different emotional angle (e.g., time-saving vs cost-saving vs status)
- `pain_points` must be specific to the target user, not generic
- If Level 3 AND monetize hypotheses exist: add `pricing_amount` (number) and `pricing_model` (subscription | one-time | usage-based | freemium) fields to each variant. These are documented in the canonical variant schema at `.claude/templates/experiment-yaml.md` `variants` section (#1117 reconciled the divergence — they are no longer orphan fields). `validate-experiment.py` enforces presence under these conditions.

### STOP 3: Variant Distinctiveness Review

Before assembling the final experiment.yaml, apply spec-reasoning.md section 4:

1. **Variant Differentiation Criteria** (section 4): Evaluate each variant pair against the differentiation checklist.

Present the variants for review:

```
Variant Distinctiveness Review
------------------------------
  [pass/warn/fail] >30% word difference: [pairwise comparison results]
  [pass/warn/fail] Different emotional angles: [angle per variant]
  [pass/warn/fail] Specific pain points: [concrete vs generic?]
  [pass/warn/fail] Action-oriented CTAs: [each starts with verb?]
  [pass/warn/fail] No obvious winner: [balanced quality?]

Variants:
  [slug] — "[headline]" (angle: [emotional angle])
  [slug] — "[headline]" (angle: [emotional angle])
  ...
```

**STOP.** Wait for user to choose variant strategy before proceeding to Step 6.

**POSTCONDITIONS:**
- 3-5 variants generated with all required fields
- Headlines have >30% word difference pairwise
- Each variant targets a different emotional angle
- Variant distinctiveness review presented
- User approved variants

**VERIFY:**
```bash
python3 -c "import yaml; d=yaml.safe_load(open('experiment/experiment.yaml')); vs=d.get('variants',[]); assert isinstance(vs, list) and len(vs)>0, 'no variants'; assert all(v.get('slug') for v in vs), 'variant missing slug'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh spec 5
```

**NEXT:** Read [state-6-stack-funnel.md](state-6-stack-funnel.md) to continue.
