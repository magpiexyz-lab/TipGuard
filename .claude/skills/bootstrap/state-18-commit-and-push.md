# STATE 18: COMMIT_AND_PUSH

**PRECONDITIONS:**
- ON-TOUCH persisted (STATE 17 POSTCONDITIONS met)
- Checkpoint is `awaiting-verify`

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
>
> State-specific logic below takes precedence.

Follow gate execution procedure per `procedures/gate-execution.md`.

- Stage files: `git add -A` (safe -- `.gitignore` excludes `.env.local`, `.runs/gate-verdicts/`, and sensitive patterns). Verify: `git diff --cached --name-only | grep -iE '\.env\.local|\.key$|\.pem$|credentials|\.secret$|\.token$|service-account' && echo "STOP: secrets staged" || echo "OK"`.
- Write `.runs/commit-message.txt`: `Bootstrap scaffold from experiment.yaml` (imperative mood). This file is the source of truth the BG4 gate checks — write it BEFORE spawning the gate so the gate can read it.
- Do NOT write `pr-title.txt` or `pr-body.md` -- the PR is created later by `/verify` in bootstrap-verify mode.
- **BG4 PR Gate**: Spawn the `gate-keeper` agent (`subagent_type: gate-keeper`). Pass: "Execute BG4 PR Gate. Verify: on feature branch (not main), pending commit message in `.runs/commit-message.txt` follows imperative mood convention." If gate-keeper returns BLOCK, fix blocking items before proceeding.
### Q-score

Compute bootstrap execution quality (see `.claude/patterns/skill-scoring.md`):

```bash
RUN_ID=$(python3 -c "import json; print(json.load(open('.runs/bootstrap-context.json')).get('run_id', ''))" 2>/dev/null || echo "")
GATES_PASSED=$(ls .runs/gate-verdicts/bg*.json 2>/dev/null | wc -l | tr -d ' ')
Q_GATES=$(python3 -c "print(round(int('${GATES_PASSED}') / max(4, 1), 3))")
PAYLOAD=$(Q_GATES_ENV="$Q_GATES" python3 -c "
import json, os
print(json.dumps({
    'scope': 'bootstrap',
    'dims': {'gates': float(os.environ['Q_GATES_ENV']), 'completion': 1.0}
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/q-dimensions.json \
  --payload "$PAYLOAD" \
  --skill bootstrap || true
```

- Delete `.runs/current-visual-brief.md` (keep `.runs/current-plan.md` -- `/verify` needs it)
- Tell the user: "Bootstrap commit ready. Proceeding to verification..." If archetype is `cli` and surface is not `none`, add: "After merging, run `/deploy` for the marketing surface, then `npm publish` for the CLI binary. To verify the publish: run `npm info <package-name>` (where `<package-name>` is the `name` field from experiment.yaml) to confirm the version is live. If `npm publish` fails, check `npm whoami` — if not logged in, run `npm login` first. After publishing and collecting usage data, run `/iterate` to review metrics, or `/retro` when ready to wrap up." If archetype is `cli` and surface is `none`, add: "After merging, run `npm publish` for the CLI binary (no surface to deploy). To verify the publish: run `npm info <package-name>` (where `<package-name>` is the `name` field from experiment.yaml) to confirm the version is live. If `npm publish` fails, check `npm whoami` — if not logged in, run `npm login` first. After publishing and collecting usage data, run `/iterate` to review metrics, or `/retro` when ready to wrap up."

Check off in `.runs/current-plan.md`: `- [x] BG4 PR Gate passed`

**POSTCONDITIONS:**
- All files staged (`git add -A` complete)
- BG4 PR Gate verdict is PASS
- `.runs/commit-message.txt` written (no `pr-title.txt` or `pr-body.md`)
- `.runs/q-dimensions.json` written
- `.runs/current-visual-brief.md` deleted

**VERIFY:**
```bash
python3 -c "import json,os; g=json.load(open('.runs/gate-verdicts/bg4.json')); assert g.get('verdict')=='PASS', 'BG4 verdict is %s' % g.get('verdict'); assert os.path.isfile('.runs/commit-message.txt'), 'commit-message.txt missing'; json.load(open('.runs/q-dimensions.json'))"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 18
```

**NEXT:** Read [state-19a-verify-prep.md](state-19a-verify-prep.md) to continue.
