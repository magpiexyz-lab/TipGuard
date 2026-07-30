# STATE 3b: DUPLICATE_CHECK

**PRECONDITIONS:**
- BG1 PASS (STATE 3a POSTCONDITIONS met)

**ACTIONS:**

1. Detect the GitHub org: run `gh repo view --json owner --jq '.owner.login'`.
   If this fails (not a GitHub repo, or `gh` not authed), skip this entire state silently.

2. Update the repo description with experiment.yaml `name` and `description` (first line):
   ```bash
   gh repo edit --description "<experiment.yaml name>: <first line of description>"
   ```
   If this fails, warn but continue — description is cosmetic.

3. Hard check — name collision:
   Run `gh repo list <org> --json name,url --limit 200 --no-archived`.
   If any repo name exactly matches experiment.yaml `name` AND is not the current repo,
   stop: "A repo named '<name>' already exists in <org>: <url>. Pick a different
   `name` in experiment.yaml or confirm with the team that this is intentional."

4. Soft check — LLM-filtered duplicate detection:
   Run `gh repo list <org> --json name,description,url --limit 200 --no-archived`.
   Exclude the current repo from the list. Review the remaining repo names and
   descriptions against the current experiment.yaml (`name`, `description`,
   `target_user`). Identify repos that appear to solve a substantially similar
   problem for a similar audience.

   If no suspicious matches -> proceed silently.

   If suspicious matches found -> present them:

   > **Potential overlaps detected.** These existing experiments may overlap with yours:
   >
   > | Repo | Description | Link |
   > |------|-------------|------|
   > | ... | ... | https://github.com/\<org\>/... |
   >
   > **Why these flagged:** [1-sentence reason per repo]
   >
   > If these are intentionally different (different audience, angle, or distribution),
   > proceed. If this is an accidental duplicate, stop and coordinate with the team.

   Wait for user confirmation before proceeding.

- **Record completion** in `bootstrap-context.json`:
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  ctx = json.load(open('.runs/bootstrap-context.json'))
  ctx['duplicate_check_done'] = True
  print(json.dumps(ctx))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/bootstrap-context.json \
    --payload "$PAYLOAD" \
    --skill bootstrap
  ```

**POSTCONDITIONS:**
- No name collision found, OR user confirmed intentional overlap
- Repo description updated (or skipped if gh unavailable)
- `duplicate_check_done` field set to `true` in `bootstrap-context.json`

**VERIFY:**
```bash
python3 -c "import json; assert json.load(open('.runs/bootstrap-context.json')).get('duplicate_check_done') == True, 'duplicate_check_done not set'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 3b
```

**NEXT:** Read [state-4-check-preconditions.md](state-4-check-preconditions.md) to continue.
