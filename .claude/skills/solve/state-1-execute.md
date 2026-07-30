# STATE 1: EXECUTE

**PRECONDITIONS:**
- Problem statement and depth mode determined (STATE 0 POSTCONDITIONS met)

**ACTIONS:**

Follow `.claude/patterns/solve-reasoning.md` using the selected depth mode.

Pass the problem statement verbatim -- do not reinterpret or narrow it.

- **Light mode**: Execute Steps 1-5 of solve-reasoning.md Light Mode directly in the lead agent. No subagents.
- **Full mode**: Execute Phases 1-6 of solve-reasoning.md Full Mode. Uses 4 Opus subagents across 6 phases (parallel research, constraint enumeration, user injection, solution design, critic loop, output).

If `solve-context.json` contains `problem_type = "defect"`, pass this to solve-reasoning
to activate the prevention dimension.

### RMG v2 Phase 1a Dossier (when `problem_type = "defect"`)

When the user invokes `/solve --defect` or `/solve --bug`, solve-reasoning
Phase 1a builds a Prior-Failure Dossier via
`.claude/scripts/lib/dossier_builder.py`. For `/solve`, derive the inputs
from the problem statement:

- `divergence_files` = file paths the lead extracts from
  `solve-context.json.problem_statement`. When the problem statement does
  not reference specific files (open-ended `/solve` queries), pass an empty
  list — the dossier still surfaces composite-identity matches via the
  recurrence-candidates artifact.
- `symptom_signature` = `canonicalize_symptom(problem_statement)` via
  `.claude/scripts/lib/symptom_canonicalizer.py`. This collapses line/col
  positions, PR/issue numbers, ISO timestamps, absolute paths, and short
  SHAs so paraphrased reports collide.

The dossier flows transparently into Phase 4b — the designer must emit a
`prior_failure_response[]` for every dossier entry citing a concrete delta
step or guard artifact absent from the prior commit (R2-A2). Empty dossier
→ Phase 4b is a no-op.

- **Step 0 — Build Prior-Failure Dossier** (Issue #1415). `state-registry.json`
  `solve.1` VERIFY asserts `.runs/prior-failure-dossier.json` exists. For
  `problem_type=defect` runs, build via the dossier helper; for non-defect
  runs, write an empty-shape dossier so the file exists (helper's no-op path
  keeps fresh-project legitimacy):

  ```bash
  # $ARGUMENTS is the canonical problem source from state-0. Prefer ctx field
  # when set (state-0 may persist it); fall back to env-var pass for runs where
  # state-0 only kept it in working memory.
  DOSSIER=$(SOLVE_ARGS="$ARGUMENTS" python3 -c "
  import json, os, re, sys
  sys.path.insert(0, '.claude/scripts/lib')
  from dossier_builder import build_dossier
  from symptom_canonicalizer import canonicalize_symptom
  ctx = json.load(open('.runs/solve-context.json'))
  if ctx.get('problem_type') != 'defect':
      print(json.dumps({'phase_1a': [], 'phase_4b': [], '_meta': {'divergence_files': [], 'symptom_signature': ''}}))
      sys.exit(0)
  problem = ctx.get('problem_statement') or os.environ.get('SOLVE_ARGS','')
  # Heuristic: extract file paths referenced in the problem statement
  files = sorted({f for f in re.findall(r'[A-Za-z0-9_./-]+\.[A-Za-z]{1,4}', problem) if '/' in f})
  symptom = canonicalize_symptom(problem)
  d = build_dossier(divergence_files=files, symptom_signature=symptom, project_dir='.')
  print(json.dumps(d))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/prior-failure-dossier.json \
    --payload "$DOSSIER" \
    --skill solve
  ```

- **Write solve trace artifact** (`.runs/solve-trace.json`) using the contract from solve-reasoning.md:
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  ctx = json.load(open('.runs/solve-context.json'))
  trace = {
      'mode': '<light|full>',
      'problem_decomposition': '<problem statement and scope>',
      'constraint_enumeration': '<constraints identified>',
      'phase_3_gaps': '<Phase 3 gap questions, self-answers, and HIGH/LOW confidence tags (full mode); empty string for light mode>',
      'solution_design': '<chosen approach and rationale>',
      'self_check': '<revision pass results>',
      'output': '<recommended solution summary>'
  }
  # Add prevention_analysis only when problem_type is defect
  if ctx.get('problem_type') == 'defect':
      trace['prevention_analysis'] = {
          'problem_type': 'defect',
          'root_cause_addressed': True,
          'recurrence_risk': '<none|guarded|unguarded>',
          # RMG v2 typed schema — see .claude/scripts/lib/recurrence_guard_parser.py.
          # None when recurrence_risk == 'none'; otherwise a dict:
          #   {"kind": "test|lint|hook|invariant|none",
          #    "artifact": "<path-or-rule-id>" | None,
          #    "rationale": "<≤200ch>",
          #    "unguardability_rationale": "<≥80ch, only when kind == 'none'>"}
          'recurrence_guard': None,
          'scope': {'all_covered': True, 'instance_count': 0},
          # Falsification Gate (required when problem_type=='defect', any kind).
          # Parsed by .claude/scripts/lib/recurrence_guard_parser.parse_falsification.
          # Schema: 3 text fields each ≥40 chars; strength in {high,low,untestable};
          # prediction vs opposite_prediction token-Jaccard < 0.8 (no tautology).
          'falsification': {
              'prediction': '<≥40 chars: signal H predicts to observe>',
              'opposite_prediction': '<≥40 chars: signal ¬H would predict instead>',
              'observable_signal': '<≥40 chars: actual observation cited from evidence>',
              'strength': '<high|low|untestable>'
          }
      }
      # RMG v2 Phase C: Prior-Failure Response. One entry per Phase 1a
      # dossier entry; each entry cites a concrete delta step or guard
      # artifact absent from the prior commit (R2-A2). Empty when dossier
      # was empty.
      trace['prior_failure_response'] = []
      # OARC #1468/#1456 — Prior-Failure Consultation. One entry per Phase 1a
      # dossier entry where `designer_consultation_attestation_required: true`
      # (semantic-match heuristic: ≥2 content-token overlap with canonicalized
      # symptom AND ≥1 file overlap). For attestation_required entries the
      # designer MUST emit consulted_via != 'skipped' OR skip_justification ≥40
      # chars. Other entries (advisory git-sentinels + ledger entries) may also
      # appear here for completeness. Empty when no dossier entry sets the
      # annotation. Enforced by verify-recurrence-guard.py --require-dossier
      # in warn mode during soak; Phase C cutover via CONSULTATION_DENY=1.
      # Schema: [{prior_run_id, consulted_via: git_show|read_pr|skipped, skip_justification}]
      trace['prior_failure_consultation'] = []
  print(json.dumps(trace))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/solve-trace.json \
    --payload "$PAYLOAD" \
    --skill solve
  ```

- **Write solve challenge artifact** (`.runs/solve-challenge.json`) — closes
  the contract from `solve-reasoning.md` Phase 5 ("Store in the caller's
  challenge artifact: /solve: .runs/solve-challenge.json"). Counts come from
  the live solve-critic.json (round-2 if it ran) and the round-1 sidecar
  archive (`.runs/solve-critic-round1.json` per #1331). For light mode or
  full mode without critic, all counts are 0:

  ```bash
  PAYLOAD=$(python3 -c "
  import json, os
  sc_path = '.runs/agent-traces/solve-critic.json'
  critic_rounds = 0
  r1_count = 0
  r2_count = 0
  if os.path.exists(sc_path):
      try:
          sc = json.load(open(sc_path))
          critic_rounds = sc.get('round', 0)
          if critic_rounds == 2:
              # round-1 counts come from the archived sidecar
              arc_path = '.runs/solve-critic-round1.json'
              if os.path.exists(arc_path):
                  arc = json.load(open(arc_path))
                  r1_count = arc.get('type_a_count', 0)
              r2_count = sc.get('type_a_count', 0)
          elif critic_rounds == 1:
              r1_count = sc.get('type_a_count', 0)
      except Exception:
          pass
  challenge = {
      'critic_rounds': critic_rounds,
      'round_1_type_a_count': r1_count,
      # always emit; 0 when critic_rounds <= 1 — registry contract
      'round_2_type_a_count': r2_count,
      # /solve does not maintain a separate challenges[] array; counts only
      'concerns': []
  }
  print(json.dumps(challenge))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/solve-challenge.json \
    --payload "$PAYLOAD" \
    --skill solve
  ```

**POSTCONDITIONS:**
- Solution analysis completed per solve-reasoning.md
- Output formatted per solve-reasoning.md Phase 6 (full mode) or Step 5 (light mode)
- `.runs/solve-trace.json` exists with required fields and `run_id` matching `solve-context.json`
- `.runs/solve-challenge.json` exists with `critic_rounds`, `round_1_type_a_count`, `round_2_type_a_count`, `concerns`

**VERIFY:**
```bash
python3 .claude/scripts/verify-recurrence-guard.py --require-phase-3-gaps --require-run-id --require-falsification --require-dossier --skill solve && python3 -c "import json,os; d=json.load(open('.runs/solve-challenge.json')); assert isinstance(d.get('critic_rounds'), int), 'critic_rounds missing or not int'; assert isinstance(d.get('round_1_type_a_count'), int), 'round_1_type_a_count missing or not int'; assert isinstance(d.get('round_2_type_a_count'), int), 'round_2_type_a_count missing or not int'; assert isinstance(d.get('concerns'), list), 'concerns missing or not list'; cr=d.get('critic_rounds',0); arc='.runs/solve-critic-round1.json'; assert cr!=2 or (os.path.exists(arc) and json.load(open(arc)).get('round')==1), '#1331 sidecar archive missing or wrong round'" && python3 -c "import json; json.load(open('.runs/prior-failure-dossier.json'))"  # .runs/solve-trace.json, .runs/solve-challenge.json, .runs/solve-critic-round1.json, .runs/prior-failure-dossier.json
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh solve 1
```

**NEXT:** Read [state-2-output.md](state-2-output.md) to continue.
