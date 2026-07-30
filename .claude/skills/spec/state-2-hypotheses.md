# STATE 2: HYPOTHESES

**PRECONDITIONS:**
- Research completed (STATE 1 POSTCONDITIONS met)

**ACTIONS:**

### STOP 1: Pre-flight Reasoning

Before proceeding to hypothesis generation, apply spec-reasoning.md section 1:

1. **Pre-flight Research Dimensions** (section 1): Evaluate the pre-flight research against all 4 dimension checklists (market, problem, competition, icp).

Present the reasoning results:

```
Pre-flight Reasoning
--------------------
  [pass/caution/fail] Market:      [verdict] [summary]   (confidence: high/medium/low)
  [pass/caution/fail] Problem:     [verdict] [summary]   (confidence: high/medium/low)
  [pass/caution/fail] Competition: [verdict] [summary]   (confidence: high/medium/low)
  [pass/caution/fail] ICP:         [verdict] [summary]   (confidence: high/medium/low)
```

**STOP.** Wait for user confirmation before proceeding to hypothesis generation.

## Step 3: Generate Hypotheses

Generate 5-10 hypotheses spanning these categories:

| Category | What it tests | Example |
|----------|--------------|---------|
| `demand` | Do people want this? | "At least N% of landing visitors will click the CTA" |
| `reach` | Can we find these people? | "We can acquire N visitors from [channel] in [time]" |
| `activate` | Can the user complete the core action? | "Core feature can be built with [stack] in [time]" |
| `monetize` | Will people pay? | "N% of active users will start a checkout" |
| `retain` | Will people come back? | "N% of users return within 7 days" |

### Hypothesis fields

Two shapes — testable hypotheses (status: pending) carry `metric:`,
desk-resolved research hypotheses (status: resolved) carry `evidence:`
instead. See `.claude/templates/experiment-yaml.md` `hypotheses` section
for the canonical schema (Issue #1117).

**Testable hypothesis (status: pending):**
```yaml
- id: h-01                       # Sequential zero-padded: h-01, h-02, ...
  category: demand               # demand | reach | activate | monetize | retain
  statement: "..."               # Testable claim with specific numbers
  metric:
    formula: "event_a / event_b" # Use <object>_<action> snake_case names aligned with your behaviors
    threshold: 0.05              # Numeric pass/fail value (e.g., 0.05 for 5%)
    operator: gte                # gt | gte | lt | lte
  priority_score: 80             # 0-100, higher = test first
  experiment_level: 1            # Minimum level needed to test this (1, 2, or 3)
  depends_on: []                 # List of hypothesis IDs this depends on
  status: pending                # pending | resolved
```

**Desk-resolved hypothesis (status: resolved, Issue #1117):**
Research-type hypotheses validated by desk research (market sizing,
competitor scans, ICP interviews) have no analytics-event formula because
they were validated before any product was built. Use `evidence:` instead
of `metric:` — `validate-experiment.py` accepts either shape, depending
on `status`. Forcing a placeholder `metric.formula` like
`research_market_exists / one` produces orphan event references that
mislead downstream consumers.

```yaml
- id: h-07
  category: demand               # market/problem -> demand; competition/ICP -> reach
  statement: "TAM exceeds $50M based on Q1 2026 market analysis"
  evidence:
    source: "TAM analysis Q1 2026"
    verdict: "TAM = $73M (target $50M+) — pass"
    citation: "internal/research/tam-q1-2026.md"
  priority_score: 60
  experiment_level: 1
  depends_on: []
  status: resolved
```

### Rules
- Research-type hypotheses from Step 2 are included with `status: resolved` and their verdicts. They must use `h-NN` IDs continuing the sequence after pending hypotheses (e.g., if pending hypotheses are h-01 through h-06, research hypotheses start at h-07). Assign the closest valid funnel category: market/problem research → `demand`, competition/ICP research → `reach`. The `research_<dimension>` IDs from STATE 1 are for the research artifact only — they are renumbered when added to the hypotheses list.
- Every **testable** hypothesis (status: pending) MUST have a `metric:` object with numeric `threshold`, `formula` using `<object>_<action>` snake_case event names (these become EVENTS.yaml entries in STATE 6), and an `operator` — no vague language. **Resolved** hypotheses (status: resolved, validated by desk research) carry `evidence:{source,verdict,citation}` instead — no formula needed because no event ever fires for them. See the canonical schema at `.claude/templates/experiment-yaml.md` `hypotheses` section (#1117).
- Filter: only include hypotheses where `experiment_level <= selected level`
- Counts below are for **pending** hypotheses only (require building product + real user data). The 4 resolved research hypotheses from Step 2 are separate and don't count toward these minimums.
- At least one hypothesis per required category:
  - Level 1: demand, reach (minimum 2 pending)
  - Level 2: demand, reach, activate, retain (minimum 4 pending)
  - Level 3: all five categories (minimum 5 pending)
- Maximum pending hypotheses: level minimum + 2. Extra hypotheses must test genuinely independent risks, not rephrasings of existing ones.
- `monetize` hypotheses appear at Level 2+ but are only *required* at Level 3
- Sort by `priority_score` descending

### STOP 2: Hypothesis Quality Review

Before deriving behaviors, apply spec-reasoning.md section 2:

1. **Hypothesis Generation Rules** (section 2): Evaluate each hypothesis against the quality checklist.

Present the hypotheses for review:

```
Hypothesis Quality Review
-------------------------
  [pass/warn/fail] Metric structure: [all have formula, numeric threshold, and operator?]
  [pass/warn/fail] Grounded thresholds: [based on benchmarks/data or guesswork?]
  [pass/warn/fail] Formula references: [formulas use valid <object>_<action> snake_case event names?]
  [pass/warn/fail] Category coverage: [all required categories present?]
  [pass/warn/fail] No duplicates: [each tests independent risk?]
  [pass/warn/fail] Dependencies explicit: [depends_on correctly set?]
  [pass/warn/fail] Falsifiable: [each can clearly fail?]
  [pass/warn/fail] Level-appropriate: [no out-of-scope categories?]

Hypotheses:
  h-01 [CATEGORY] "statement" — metric: [formula] [operator] [threshold]
  h-02 [CATEGORY] "statement" — metric: [formula] [operator] [threshold]
  ...
```

**STOP.** Wait for user review before proceeding to Step 4.

**POSTCONDITIONS:**
- Pre-flight reasoning reviewed and user confirmed
- 5-10 hypotheses generated spanning required categories for the selected level
- Each hypothesis has id, category, statement, metric (formula, threshold, operator), priority_score, experiment_level, depends_on, status
- Hypothesis quality review presented
- User approved hypotheses

**VERIFY:**
```bash
python3 -c "import yaml; d=yaml.safe_load(open('experiment/experiment.yaml')); hs=d.get('hypotheses',[]); assert isinstance(hs, list) and len(hs)>0, 'no hypotheses'; assert all(h.get('id') and h.get('category') and h.get('statement') for h in hs), 'hypothesis missing required fields'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh spec 2
```

**NEXT:** Read [state-3-behaviors.md](state-3-behaviors.md) to continue.
