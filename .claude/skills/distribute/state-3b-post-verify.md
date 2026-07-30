# STATE 3b: POST_VERIFY

**PRECONDITIONS:**
- STATE 3a POSTCONDITIONS met (verify-report.md exists)

**ACTIONS:**

### Commit to branch

- You are already on a `chore/distribute-*` branch
- Commit all changes with message: imperative mood describing the implementation (e.g., "Add UTM/gclid capture and feedback widget for distribution")
- Do NOT create a PR yet (that happens in State 5)

### Working memory for PR body (State 5)

Store the following in working memory for inclusion in the PR body during State 5:

**Demo mode recommendation:**
If the app requires signup/auth before the user can see value, note a recommendation for a demo/preview mode. This is a recommendation only — implementing the demo is a separate `/change` task.

**Conversion sync setup instructions:**
Read the selected channel's stack file "Setup Instructions" section and prepare step-by-step instructions. Also read the analytics stack file for provider-specific destination/integration instructions.

**Ads Dashboard Setup:**
Read the analytics stack file's Dashboard Navigation section for provider-specific terminology, then prepare these instructions:

1. Go to the analytics dashboard -> New dashboard -> "Ads Performance: {project_name}"
2. Add these insights (read the channel's stack file "UTM Parameters" section for the correct `utm_source` value):
   - **Traffic by Source**: Trend chart, event `visit_landing`, breakdown by `utm_source`, last 7 days
   - **Paid Funnel**: Funnel chart, events `visit_landing` (filtered: utm_source = {channel_source}) -> `signup_complete` -> `activate`, last 7 days
   - **Cost per Activation**: Number (manual calculation) — Total channel spend / activate count where utm_source = {channel_source}
   - **Feedback Summary**: Trend chart, event `feedback_submitted`, breakdown by `source` property, last 7 days

**POSTCONDITIONS:**
- All changes committed to branch with imperative message
- PR body working memory prepared for State 5

**VERIFY:**
```bash
git log -1 --format=%B | head -1 | grep -v '^Merge'
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh distribute 3b
```

**NEXT:** Read [state-4-generate.md](state-4-generate.md) to continue.
