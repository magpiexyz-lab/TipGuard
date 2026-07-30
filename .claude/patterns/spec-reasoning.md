# Spec Reasoning Rules

Pure reasoning rules for evaluating experiment specifications. Each section provides structured criteria that consumers reference by section number and apply at their own checkpoints.

## 1. Pre-flight Research Dimensions

Evaluate whether the idea has sufficient real-world grounding across 4 dimensions. Each dimension outputs: `verdict` (pass/caution/fail), `confidence` (high/medium/low), `summary` (1-2 sentences).

### Market

**Checklist:**
- [ ] **Addressable market identified**: Can you name a specific, bounded group of potential users? (e.g., "freelance designers billing 1-5 clients/month" not "freelancers")
- [ ] **Active spending**: Are people currently paying money or significant time to solve this problem? Name at least one existing solution they pay for.
- [ ] **Market signals**: At least 2 of: forum threads discussing the pain, competitor reviews mentioning gaps, job postings for this function, industry reports sizing the segment.
- [ ] **Not a shrinking market**: The problem isn't being eliminated by a platform change, regulation, or technology shift.

**Red flags:**
- Market exists only in theory (no evidence of current spending/time investment)

### Problem

**Checklist:**
- [ ] **Pain specificity**: The problem is described with concrete details (frequency, time lost, cost incurred), not abstract frustrations
- [ ] **Multiple sources**: Pain is validated from 2+ independent sources (forums, reviews, interviews, support tickets) — not just one person's experience
- [ ] **Currently exists**: The problem is happening right now, not a predicted future pain

**Red flags:**
- Only evidence is the founder's personal experience (sample size of 1)
- Aspirational problem — users say they "should" solve it but aren't actively trying to

### Competition

**Checklist:**
- [ ] **Competitors identified**: Named at least 2 existing alternatives (direct or indirect — includes spreadsheets, manual processes, hiring someone)
- [ ] **Gap articulated**: One specific thing competitors do poorly or don't do at all, validated by user complaints (reviews, forum posts, support tickets)
- [ ] **Differentiation is user-facing**: The difference matters to the target user, not just technically interesting. "Faster" must be measurably faster at a task users care about.
- [ ] **Not just cheaper**: Price-only differentiation is fragile. At least one non-price advantage exists.
- [ ] **Timing advantage**: Why now? Something changed (new API, regulation, market shift, unserved niche) that makes this solvable today in a way it wasn't before.

**Red flags:**
- No competitors found (usually means no market, not a blue ocean)
- Differentiation requires explaining — if the user can't see the difference in 5 seconds, it's not differentiated enough for an MVP
- "We'll do it better" without specifying what "better" means concretely

### ICP

**Checklist:**
- [ ] **Describable person**: You can name a specific role, context, and constraint — not just a demographic (e.g., "freelance designers billing 1-5 clients/month who use Figma" not "designers")
- [ ] **Reachable via chosen channels**: Can you reach 100+ target users through the planned distribution channels within the experiment window?

**Red flags:**
- Target user is too broad to reach efficiently ("anyone who..." is not an ICP)

## 2. Hypothesis Generation Rules

Evaluate whether hypotheses are testable and well-structured.

**Checklist:**
- [ ] **Each hypothesis has a numeric threshold**: "5% CTR" not "good conversion rate"
- [ ] **Thresholds are grounded**: Based on industry benchmarks, competitor data, or first-principles calculation — not arbitrary round numbers
- [ ] **Categories covered**: All required categories for the selected level have at least one pending hypothesis
- [ ] **No duplicates**: Each hypothesis tests a genuinely independent risk. "Users will sign up" and "Users will create an account" test the same thing.
- [ ] **Dependencies are explicit**: If hypothesis B can't be tested until hypothesis A is validated, `depends_on` reflects this
- [ ] **Falsifiable**: Each hypothesis can clearly fail. "Users will find value" is not falsifiable; "5+ users complete an invoice within 7 days" is.
- [ ] **Level-appropriate**: No monetize hypotheses at Level 1, no retain hypotheses if the experiment window is <7 days

**Red flags:**
- All thresholds are round numbers (50%, 100 users) — suggests guessing, not reasoning
- More than level minimum + 2 hypotheses — scope creep, testing too many things at once
- Hypothesis that can only be confirmed, never rejected (survivorship bias)

### Generation rules

- **Category-to-funnel mapping**: reach/demand -> L1, activate -> L2, monetize -> L2 (signal only), retain -> L3
- **Threshold sourcing priority**: industry benchmark > competitor data > first-principles calculation
- **Priority score** (0-100): higher uncertainty = higher priority. Hypotheses where failure is most likely or most consequential are tested first.
- **Dependency tracking**: `depends_on` is required when hypothesis B needs A's behavior to exist before it can be tested (e.g., activate depends on demand being validated)
- **Per-level pending counts**: L1 min 2 / max 4, L2 min 4 / max 6, L3 min 5 / max 7

## 3. Behavior Traceability Rules

Evaluate whether behaviors correctly map to hypotheses.

**Checklist:**
- [ ] **Every pending hypothesis has >=1 behavior**: No hypothesis is left without an observable test
- [ ] **Every behavior traces to a hypothesis**: No orphan behaviors that don't validate anything
- [ ] **Behaviors are observable**: Each maps to an analytics event, database state change, or user-visible action
- [ ] **Tests are verifiable**: Each behavior's `tests` list contains assertions that can be automated (page renders X, clicking Y navigates to Z)
- [ ] **No implementation leakage**: Behaviors describe WHAT the user does, not HOW the code works ("user creates an invoice" not "API endpoint returns 200")

## 4. Variant Differentiation Criteria

Evaluate whether variants test genuinely different angles.

**Checklist:**
- [ ] **>30% word difference**: Compare each pair of headlines — they must differ by more than 30% of words (not just synonyms or reordering)
- [ ] **Different emotional angles**: Each variant targets a distinct motivation (e.g., time-saving vs cost-saving vs status vs fear-of-missing-out)
- [ ] **Pain points are specific**: Each variant's 3 pain points reference concrete situations the target user experiences, not generic problems
- [ ] **CTAs are action-oriented**: Each CTA starts with a verb and implies an outcome ("Start invoicing free" not "Learn more")
- [ ] **No variant is clearly superior**: If one variant is obviously better than others, the test won't produce useful signal — strengthen the weaker variants

**Red flags:**
- Headlines differ only by a word or two ("Save Time on Invoicing" vs "Save Hours on Invoicing")
- All variants use the same emotional angle (three versions of "save time")
- Pain points are copy-pasted across variants with minor edits
- A variant's headline doesn't connect to its pain points (messaging mismatch)

### Additional criteria

- Minimum 3 variants required
- Each variant must present a unique angle — no two variants should share the same primary pain point
- If any pair of variants could be confused by a reader, they are not differentiated enough

## 5. Funnel Threshold Derivation

Rules for deriving funnel thresholds from hypotheses.

### Level-to-dimension availability

| Level | Available dimensions |
|-------|---------------------|
| L1 | REACH, DEMAND |
| L2 | + ACTIVATE, MONETIZE (signal only) |
| L3 | + RETAIN |

### Threshold derivation

- The threshold for each funnel dimension is the `metric.threshold` from the highest-priority hypothesis in that category
- If multiple hypotheses share the same category, use the one with the highest `priority_score`
- Resolved (research) hypotheses do not contribute thresholds — only pending hypotheses with real metrics

### Decision framework

| Verdict | Condition |
|---------|-----------|
| **scale** | All tested dimensions >= 1.0x threshold |
| **kill** | Any top-funnel (REACH or DEMAND) < 0.5x threshold |
| **pivot** | 2+ dimensions < 0.8x threshold |
| **refine** | 1+ dimensions < 1.0x threshold but fewer than 2 below 0.8x |

## 6. Stack Selection Rules

Evaluate whether the stack matches the experiment's needs.

**Checklist:**
- [ ] **Level-appropriate stack**: Level 1 has no database/auth, Level 2 adds database, Level 3 adds auth (and payment if monetize hypotheses exist)
- [ ] **No over-engineering**: Stack components match what's needed to test the hypotheses, not what would be needed at scale
- [ ] **Distribution-compatible**: The stack supports the planned distribution channels (e.g., if targeting paid ads, analytics must be present for conversion tracking)
- [ ] **Testing-compatible**: `stack.testing` is present
- [ ] **No conflicting stacks**: No incompatible combinations (e.g., Playwright with service archetype)

### Type-to-archetype mapping

| Product type | Archetype |
|-------------|-----------|
| Web application with UI | `web-app` |
| API / backend / agent | `service` |
| Command-line tool | `cli` |

### Level-to-stack additions

| Level | Base stack | Additions |
|-------|-----------|-----------|
| L1 | runtime, hosting, ui, analytics | (base) |
| L2 | L1 + | database |
| L3 | L2 + | auth, payment (if monetize hypotheses) |

### Hosting routing

Default hosting is Vercel. Route to Railway when any of:
- (a) AI agent or long-running background tasks
- (b) Behaviors require >30s execution, streaming responses, or persistent connections
- (c) Experiment explicitly needs a persistent server process
- (d) Database is SQLite (incompatible with Vercel's serverless architecture)

---

*These rules are referenced by section number. Consumers apply them at their own checkpoints.*
