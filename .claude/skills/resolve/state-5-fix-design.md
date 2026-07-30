# STATE 5: FIX_DESIGN

**PRECONDITIONS:**
- Blast radius complete (STATE 4 POSTCONDITIONS met)
- Root-cause clustering complete if applicable (STATE 4b POSTCONDITIONS met)

**ACTIONS:**

#### Step 0 — Build Prior-Failure Dossier (RMG v2 Phase 1a; required, Issue #1415)

`resolve` always handles defects, so this step is mandatory before 5a. Builds
`.runs/prior-failure-dossier.json` which `state-registry.json` `resolve.5`
VERIFY asserts must exist — closes the prose-prescribed-but-VERIFY-unenforced
gap.

```bash
DOSSIER=$(python3 -c "
import json, sys
sys.path.insert(0, '.claude/scripts/lib')
from dossier_builder import build_dossier
from symptom_canonicalizer import canonicalize_symptom
repro = json.load(open('.runs/resolve-reproduction.json'))
# divergence_point is the string '<file>:<line>' per state-3-reproduce.md schema —
# split on first ':' to get the file path. Filter empty/missing values.
files = sorted({(r.get('divergence_point','') or '').split(':',1)[0]
                for r in repro.get('reproductions',[])
                if r.get('divergence_point')})
files = [f for f in files if f]
symptom = canonicalize_symptom('\n'.join(r.get('actual','') for r in repro.get('reproductions',[])))
d = build_dossier(divergence_files=files, symptom_signature=symptom, project_dir='.')
print(json.dumps(d))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/prior-failure-dossier.json \
  --payload "$DOSSIER" \
  --skill resolve
```

The dossier is consumed by `solve-reasoning.md` Phase 1a (designer-visible
reveal — minimal fields only) and Phase 4b (full reveal — designer emits
`prior_failure_response[]`).

#### 5a) Complexity assessment

Determine solve-reasoning depth:

```
solve_depth = "light"  # default
if blast_radius confirmed >= 3: solve_depth = "full"
if severity = HIGH: solve_depth = "full"
```

State the depth selection with rationale before proceeding.

#### 5a-ring) Ring classification

Determine Ring level based on files the fix will modify:

| Ring | Scope | solve_depth | Behavior |
|------|-------|-------------|----------|
| Ring 1 | Only `.claude/skills/<skill>/state-*.md` | Keep existing logic (default light) | Normal fix flow |
| Ring 2 | `.claude/hooks/`, `.claude/scripts/`, `.claude/stacks/` | Force `"full"` | Normal fix flow with full depth |
| Ring 3 | `state-registry.json` structure or `CLAUDE.md` | N/A | Analysis-only — no fix designed |

**Ring 3 handling:**
- Output analysis report only (no `fix_plan`)
- In `solve-trace.json`, set `output` to: "Ring 3: requires architecture discussion — see analysis"
- In `resolve-context.json`, set `"ring": 3`
- After STATE 5d completes, skip STATEs 6-10 and jump directly to STATE 11 (commit-pr)


#### 5b-light) Light mode path

When `solve_depth = "light"`: call `.claude/patterns/solve-reasoning.md` light mode (Steps 1-5).

- Set `problem_type = "defect"` (resolve always handles defects)
- **Inputs**: `divergence_point`, `blast_radius`, `reproduction`, `severity` as constraints
- **Output mapping**:
  - "Recommended Solution" -> `root_cause`
  - "Implementation Steps" -> `fix_plan`
  - "Constraints Respected" -> constraint review
  - "Key Tradeoff" -> diagnosis report
  - "Prevention Analysis" -> `prevention_analysis` in solve-trace.json

#### 5b-full) Full mode path

When `solve_depth = "full"`: call `.claude/patterns/solve-reasoning.md` full mode (Phases 1-4). Phase 5 (critic) executes in STATE 5d.

- Set `problem_type = "defect"` (resolve always handles defects)
- **Phase 1 agent customization**:
  - Agent 1 = divergence investigation (trace the assumption violation, git blame context)
  - Agent 2 = blast radius + prior fix art (grep for the causal pattern broadly, find past fixes for similar patterns)
  - Agent 3 = fix constraints (validator compatibility, archetype universality, backwards compatibility)
- **Phase 1a Dossier (RMG v2)**: build a Prior-Failure Dossier via
  `.claude/scripts/lib/dossier_builder.py` with
  `divergence_files = union of reproductions[*].divergence_point.file` and
  `symptom_signature = canonicalize_symptom(reproductions[*].actual)`. Phase 1a
  reveals only minimal fields to the designer; Phase 4b reveals the rest and
  the designer emits `prior_failure_response`.
- **Phase 3 gap resolution**: autonomous — AI self-answers research gaps using first-principles reasoning
- **Phase 5 Critic** (STATE 5d): domain-specific vectors configured in Step 5c below, executed in STATE 5d
- **Output mapping**:
  - "Recommended Solution" -> `root_cause` + `fix_plan`
  - "Constraint Space" -> hard constraints in diagnosis report
  - "Remaining Risks" TYPE B -> system constraints in diagnosis report
  - "Remaining Risks" TYPE C -> open questions in diagnosis report
  - "Remaining Risks" Caveats -> caveats in diagnosis report
  - "Prevention Analysis" -> `prevention_analysis` in solve-trace.json

#### 5c) Domain-specific post-validation

After solve-reasoning completes (either mode), apply template-specific validation.

**Core prevention** (handled by solve-reasoning `prevention_analysis`):
Root cause, regression prevention, and scope coverage are evaluated by the core
pattern via `problem_type = "defect"`. Do not re-check these — verify via
`prevention_analysis` field in solve-trace.json:
- `root_cause_addressed` must be true
- `recurrence_risk` must be "none" or "guarded" (if "unguarded", justification
  required in `recurrence_guard`)
- `scope.all_covered` must be true

If core prevention fails: iterate once through solve-reasoning self-check (light)
or flag for Phase 5 critic (full).

**Domain-specific requirement** (must be satisfied):
1. **Template universality**: Fix works for ALL experiment.yaml configurations
   (all archetypes, with/without optional stacks)

If template universality fails: iterate once.

**Falsification authoring** (Falsification Gate — required for every defect run,
all `recurrence_guard.kind` values including `none`):
Per fix or cluster, author a `falsification` block inside `prevention_analysis`.
This forces a falsifiable claim — what observable signal would ¬H produce that
H wouldn't? The block is independent of `recurrence_guard.kind` because the
mechanism is reasoning discipline, not test coverage. Even prose-only fixes
(kind=none) require the textual `prediction / opposite_prediction /
observable_signal / strength` quartet. Schema: see
`.claude/patterns/solve-reasoning.md` "Falsification Schema". solve-critic
vector 7 (`falsification-weak`) will challenge weak or circular framing in
STATE 5d; structural overlap (token-Jaccard ≥ 0.8 between `prediction` and
`opposite_prediction`) is rejected at parse time.

Record: `root_cause`, `fix_plan` (per-file changes), `proposed_checks` (if any
from prevention_analysis.recurrence_guard), `falsification` (see above).

- **Write solve trace artifact** (`.runs/solve-trace.json`) using the contract from solve-reasoning.md:
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  trace = {
      'mode': '<light|full>',
      'problem_decomposition': '<divergence points and blast radius summary>',
      'constraint_enumeration': '<template universality, validator compat, backwards compat>',
      'phase_3_gaps': '<Phase 3 gap questions, self-answers, and HIGH/LOW confidence tags (full mode); empty string for light mode>',
      'solution_design': '<root_cause + fix_plan for each issue/cluster>',
      'self_check': '<revision pass results>',
      'output': '<recommended fix summary>',
      'prevention_analysis': {
          'problem_type': 'defect',
          'root_cause_addressed': True,
          'recurrence_risk': '<none|guarded|unguarded>',
          # RMG v2 typed schema. When recurrence_risk == 'none', set this to None.
          # Otherwise emit a dict matching .claude/scripts/lib/recurrence_guard_parser.py:
          #   {"kind": "test|lint|hook|invariant|none",
          #    "artifact": "<path-or-rule-id>" | None,
          #    "rationale": "<≤200ch>",
          #    "unguardability_rationale": "<≥80ch, only when kind == 'none'>"}
          'recurrence_guard': None,  # replace with typed dict when risk != 'none'
          'scope': {
              'all_covered': True,
              'instance_count': 0
          },
          # Falsification Gate (required when problem_type=='defect', any kind).
          # Parsed by .claude/scripts/lib/recurrence_guard_parser.parse_falsification.
          # Schema: prediction / opposite_prediction / observable_signal each
          # ≥40 chars; strength in {high, low, untestable}; token-Jaccard
          # between prediction and opposite_prediction must be < 0.8.
          'falsification': {
              'prediction': '<≥40 chars: signal H predicts to observe — specific to root cause>',
              'opposite_prediction': '<≥40 chars: signal ¬H would predict instead — structurally distinct>',
              'observable_signal': '<≥40 chars: actual observation cited from reproduction/evidence>',
              'strength': '<high|low|untestable>'
          }
      },
      # RMG v2 Phase C: Prior-Failure Response. One entry per Phase 1a dossier
      # entry. Each entry MUST cite a concrete delta step or guard artifact
      # absent from the prior commit (R2-A2). Empty list when dossier was empty.
      # Schema:
      #   {"prior_run_id": str,
      #    "failure_mode": str,
      #    "how_addressed": str (≤300 chars),
      #    "concrete_delta_step_or_guard": str (step #N OR guard artifact path)}
      'prior_failure_response': []
  }
  print(json.dumps(trace))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/solve-trace.json \
    --payload "$PAYLOAD" \
    --skill resolve
  ```

**POSTCONDITIONS:**
- Each actionable issue (or cluster) has: `root_cause`, `fix_plan`, `proposed_checks`
- Core prevention (`prevention_analysis`) passed for all fixes
- Domain-specific template universality passed for all fixes
- `.runs/solve-trace.json` exists with required fields including `prevention_analysis`

**VERIFY:**
```bash
python3 .claude/scripts/verify-recurrence-guard.py --require-prevention --require-falsification --require-dossier --skill resolve && python3 -c "import json; json.load(open('.runs/prior-failure-dossier.json'))"  # .runs/solve-trace.json, .runs/prior-failure-dossier.json
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh resolve 5
```

**NEXT:** Read [state-5b-tier-floors.md](state-5b-tier-floors.md) to continue.
