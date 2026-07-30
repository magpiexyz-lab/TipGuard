# Step 1 Prompt: Update ux-design.md with Portfolio Intelligence

## Context

We're adding Portfolio Intelligence to Assayer — a feature that ranks experiments by Assayer Score, provides AI-generated cross-experiment recommendations, and enables budget reallocation. The research and design are documented in `docs/portfolio-distribution-design.md`. Your job is to merge that design INTO `docs/ux-design.md` so it remains the single UX source of truth.

## Instructions

Read these files first (do NOT modify them):
1. `docs/ux-design.md` — the current UX source of truth
2. `docs/portfolio-distribution-design.md` — the new design to merge in (specifically Part 2: UX Design)
3. `docs/mvp-budget-playbook.md` — reference for Assayer Score formula and benchmarks (do not merge this file; it's an operator playbook, not a UX spec)

Then modify ONLY `docs/ux-design.md` with the changes below. Do not create new files. Do not modify any other file.

## Changes Required

### 1. Screen 8: Lab — Replace existing wireframe and design decisions

Find the section `### Screen 8: Lab (Dashboard) — Portfolio View` (around line 1244).

**Replace the RUNNING group wireframe** with one that includes:
- Each RUNNING card shows `★ {score}` (Assayer Score 0-100) in the top-right corner
- RUNNING cards are sorted by Assayer Score descending (highest score = leftmost/topmost)
- Each card shows compressed dimension ratios: `R {x}x D {x}x M {x}x` (instead of only bottleneck ratio)
- Status label derived from score: 80-100 = ON TRACK, 60-79 = PROMISING, 40-59 = LOW !, 20-39 = DANGER, 0-19 = CRITICAL

**Add AI Insight card** between RUNNING and VERDICT READY groups:
- Only visible when user has 2+ RUNNING experiments AND at least one has 30+ visits
- Shows natural language AI recommendation (1-3 numbered actions)
- Each action is specific: "Kill {name} → free ${amount}" or "Double {name}'s Google Ads budget"
- Two buttons: [Apply suggestions ->] (primary) and [Dismiss] (secondary)
- Labeled as "AI INSIGHT" with a subtle gold accent

**Add [Budget] tab** in the Lab header (next to the existing experiments view):
- Tab only visible for Team plan users
- Shows portfolio budget overview: total allocated / total available + progress bar
- Table with columns: Experiment | Spent | Remaining | Score | Status
- Each row has a spend progress bar
- AI Budget Optimizer section: CURRENT → RECOMMENDED allocation with reasoning
- [Apply Rebalance ->] button and [Customize] button
- [Customize] expands to linked percentage sliders constrained to 100%, one per active experiment
- Each slider paired with a text input for exact values

**Update design decisions** to add:
5. **Assayer Score is the sort key for RUNNING experiments** — visual hierarchy communicates priority. Highest score = most investment-worthy.
6. **AI Insight appears only with sufficient data** — progressive disclosure prevents clutter for single-experiment users.
7. **Budget tab is Team-only** — advanced portfolio management as upgrade incentive.
8. **Three compressed dimension ratios per card** — richer than bottleneck-only, but still fits one line.

Keep the VERDICT READY, COMPLETED sections, empty state, and all existing design decisions unchanged.

### 2. Lab Mobile Wireframe — Add NEEDS ATTENTION sorting

Find the mobile Lab wireframe section (under `#### Lab (Mobile)` in the Per-Page Mobile Wireframes section).

Replace or add a mobile Lab wireframe that uses:
- Portfolio Health Score (★ XX) in the top-right of the page header
- Experiments grouped by urgency, NOT by state:
  - "NEEDS ATTENTION" group first (score < 20 OR verdict ready OR budget exhausted)
  - "ON TRACK" group second (all others)
- NEEDS ATTENTION cards show inline action buttons: [Kill & Free Budget] [View ->]
- ON TRACK cards are compressed: name + score + one-line status only
- Pull-to-refresh triggers score recalculation

### 3. Experiment Comparison — Add Score column and AI Recommendation

Find the `### Experiment Comparison` section (around line 1359).

Add to the comparison table:
- New row at the top: `Score` showing ★ XX per experiment
- New row: `CPA` showing cost per activation per experiment
- New section below the table: `== AI RECOMMENDATION ==` with:
  - Highlight of the strongest experiment ("★ {name} is your strongest bet")
  - 1-3 numbered specific actions
  - Buttons: [Apply All ->] [Apply #1 only] [Dismiss]

### 4. Notifications — Add Portfolio Update

Find the `### Defined touchpoints` table in the Notifications section.

Add a new row:
| 8 | Portfolio insight ready | "Portfolio Update: {N} experiments. ★ {top_name} leads at {score}." | Daily (when 2+ running) |

Add a new email template wireframe after the existing one:
- Title: "Portfolio Update — {N} experiments"
- Shows ★ Portfolio Health score
- Per-experiment row: name + score + trend arrow (↑→↓) + one-line status
- Suggested action line
- [Open Lab ->] button

### 5. Pricing Table — Update Comparison view row

Find the pricing/subscription comparison table.

Change the row currently showing `Comparison view` to show `Portfolio Intelligence` with these values:
- Free: --
- PAYG: --
- Pro: Score + AI Insight
- Team: Score + AI Insight + Budget Optimizer

### 6. Information Architecture — Update Lab subtree

Find the `Lab (Your Lab)` section in the Information Architecture block.

Replace with:
```
Lab (Your Lab)
  |-> Running (sorted by Assayer Score)
  |     |-> Per-experiment card (★ Score + R/D/M ratios)
  |     +-> AI Insight (when 2+ running, 30+ visits)
  |-> Verdict Ready (needs attention)
  |-> Completed (historical verdicts)
  |-> Linked rounds (Round 1 → Round 2)
  |-> Pivot lineage (Original → Pivot)
  |-> [Budget] tab (Team plan)
  |     |-> Portfolio budget overview
  |     |-> AI Budget Optimizer
  |     +-> Custom allocation sliders
  +-> [+ New Idea]
```

## Rules

- Keep all existing content that is not explicitly mentioned above. Do NOT remove existing wireframes, design decisions, or sections unless told to replace them.
- Maintain the same writing style, tone, and formatting conventions as the rest of ux-design.md.
- All wireframes use the same ASCII art style already established in the document.
- When adding design decisions, number them continuing from existing lists.
- The phrase "Assayer Score" must always use this exact capitalization.
- Do not add implementation details (SQL, TypeScript, API routes) — that belongs in product-design.md.
- Do not reference portfolio-distribution-design.md or mvp-budget-playbook.md in the output — ux-design.md should be self-contained.

## Verification

After editing, verify:
1. The Information Architecture section matches the new Lab structure
2. The Pricing table includes Portfolio Intelligence
3. The Notification touchpoints table has 8 rows (was 7)
4. Screen 8 wireframe shows ★ Score on cards
5. Mobile Lab wireframe uses NEEDS ATTENTION grouping
6. Comparison section has Score row and AI Recommendation
7. No orphaned references to old wireframes
