# STATE 5: APPROVE_AND_SHIP

**PRECONDITIONS:**
- Campaign config generated (STATE 4 POSTCONDITIONS met)

**ACTIONS:**

### 5a: Present ads.yaml

Present the full `experiment/ads.yaml` content to the user.

If ads.yaml contains a non-empty `sitelinks` array, present a formatted sitelink preview table after the main ads.yaml content:

> **Sitelinks Preview:**
>
> | # | Link Text | Chars | Desc 1 | Chars | Desc 2 | Chars | URL |
> |---|-----------|-------|--------|-------|--------|-------|-----|
> | 1 | {link_text} | {len} | {description_1} | {len} | {description_2} | {len} | {final_url} |
> | ... | | | | | | | |
>
> Character limits: link_text ≤ 25, descriptions ≤ 35 each.

If `sitelinks: []`, note: "No sitelinks generated (fewer than 2 qualifying destination pages)."

### 5b: STOP for approval

**STOP.** End your response here. Say:
> Review the ads config above. Reply **approve** to proceed, or tell me what to change.
> After approval, I'll open a PR and then create the campaign in Google Ads.

**Do not proceed until the user approves.**

If the user requests changes instead of approving, revise the config to address their feedback and present it again (return to STATE 4 step 4d). Repeat until approved.

### 5c: Record approval

```bash
PAYLOAD=$(python3 -c "
import json
ctx = json.load(open('.runs/distribute-context.json'))
ctx['approved'] = True
print(json.dumps(ctx))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/distribute-context.json \
  --payload "$PAYLOAD" \
  --skill distribute
```

### 5d: Write delivery artifacts

Write `.runs/commit-message.txt` — descriptive message for distribution config changes.

Write `.runs/pr-title.txt` — short title (<=70 chars).

Write `.runs/pr-body.md` using `.github/PULL_REQUEST_TEMPLATE.md` format:
  - **Summary**: what was generated and why (include the selected channel)
  - **Distribution Setup**: step-by-step channel + analytics setup instructions (from State 3 working memory — the conversion sync and dashboard setup content)
  - **What Changed**: files modified (landing page UTM capture, experiment/EVENTS.yaml, ads.yaml, FeedbackWidget)
  - The full `ads.yaml` content in the PR body for easy review
  - Fill in **every** section. Empty sections are not acceptable. If a section does not apply, write "N/A" with a one-line reason.
  - End with: `🤖 Generated with [Claude Code](https://claude.com/claude-code)`

**POSTCONDITIONS:**
- User has explicitly approved the ads config
- `approved` field set to `true` in `distribute-context.json`
- Delivery artifacts written: `.runs/commit-message.txt`, `.runs/pr-title.txt`, `.runs/pr-body.md`

**VERIFY:**
```bash
python3 -c "import json,os; assert json.load(open('.runs/distribute-context.json')).get('approved')==True; assert os.path.isfile('.runs/commit-message.txt'), 'commit-message.txt missing'; assert os.path.isfile('.runs/pr-title.txt'), 'pr-title.txt missing'; assert os.path.isfile('.runs/pr-body.md'), 'pr-body.md missing'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh distribute 5
```

**NEXT:** Read [state-6-campaign.md](state-6-campaign.md) to continue. `lifecycle-finalize.sh` handles commit, push, PR creation, and auto-merge after state 6 completes.
