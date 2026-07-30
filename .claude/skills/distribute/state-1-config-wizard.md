# STATE 1: CONFIG_WIZARD

**PRECONDITIONS:**
- Init and file validation passed (STATE 0 POSTCONDITIONS met)

**ACTIONS:**

> **Branch cleanup on failure:** Any "stop" in this step leaves you on a feature branch (created in State 0). Append cleanup boilerplate per `.claude/patterns/branch-cleanup-error-template.md` (Variant A, branch=`chore/distribute`, recovery: 'address the prerequisite, then re-run `/distribute`') to every stop message.

1. If `experiment/ads.yaml` already exists, ask: "An ads config already exists. Generate a new version (v2)?"
2. List available channels by scanning `.claude/stacks/distribution/*.md` (strip the `.md` extension to get channel names)
3. Ask: "Which distribution channel? Available: [channels]. Enter channel name:"
4. Read the selected channel's stack file at `.claude/stacks/distribution/<channel>.md`
5. Read experiment.yaml `description`
6. Match against restricted-industry keywords: `crypto`, `DeFi`, `token`, `ICO`, `blockchain`, `NFT`, `yield`, `staking`, `liquidity`, `protocol`, `wallet`, `exchange`, `mining`, `DAO`
7. If match found, read the selected channel's "Policy Restrictions" section. If the channel restricts or bans the category, warn the user: "Your experiment mentions [keyword]. [Channel] [restricts/bans] this category: [details]. Consider switching to [alternative channels that allow it]." Non-blocking — the user can confirm to proceed or switch channel.
8. Verify `stack.analytics` is present in experiment.yaml. If not, stop: "Analytics is required for distribution tracking. Add `analytics: posthog` (or another provider) to experiment.yaml `stack` and run `/change add analytics` to scaffold analytics support, then re-run `/distribute`."
9. Verify the analytics stack is configured: read the analytics stack file's `env` frontmatter. If `env.client` lists a client env var, check that it appears in `.env.example`. If the env var is not found in `.env.example`, stop: "Analytics is not configured. Verify `.env.example` contains the analytics client key, or run `/bootstrap` first to scaffold the app with analytics." If `env.client` is empty, the stack uses hardcoded keys (e.g., PostHog's shared publishable key) — skip this check.

Write all configuration results to the preconditions artifact in a single update:
```bash
PAYLOAD=$(python3 -c "
import json
p = json.load(open('.runs/distribute-preconditions.json'))
p['channel'] = '<selected channel>'
p['policy_checked'] = True
p['analytics_configured'] = True
print(json.dumps(p))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/distribute-preconditions.json \
  --payload "$PAYLOAD" \
  --skill distribute
```

**POSTCONDITIONS:**
- Channel selected and stack file read
- Policy check completed (pass or user-confirmed)
- Analytics configuration verified
- `.runs/distribute-preconditions.json` updated with fields: `channel`, `policy_checked`, `analytics_configured`

**VERIFY:**
```bash
python3 -c "import json; p=json.load(open('.runs/distribute-preconditions.json')); assert p.get('channel'); assert p.get('policy_checked'); assert p.get('analytics_configured')"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh distribute 1
```

**NEXT:** Read [state-2-validate-analytics.md](state-2-validate-analytics.md) to continue.
