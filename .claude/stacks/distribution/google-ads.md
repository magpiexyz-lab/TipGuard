---
assumes: []
packages:
  runtime: []
  dev: []
files: []
env:
  server: []
  client: []
ci_placeholders: {}
clean:
  files: []
  dirs: []
gitignore: []
---
<!-- coherence-allow: raw-golden_path (sequence-step) scope=["## Ad Format Constraints", "## Phase 1 Playbook"] — google-ads sitelinks are derived from golden_path step descriptions in funnel order (landing → value → retention) for click priority. Ad Format Constraints documents the derivation; Phase 1 Playbook's Sitelink Strategy subsection (### Sitelink Strategy) uses it. LIST semantics, not SET. -->

# Distribution: Google Ads
> Used when `/distribute` is run with channel `google-ads`
> Assumes: None — distribution stacks create no source code or packages; they generate config only
> Team-facing playbook docx: generated from this file's Phase 1 / Phase 2 / Cost Model sections via `make playbook-docx` (`scripts/generate_playbook_docx.py`) — regenerate and reshare after editing the playbook; never hand-edit the docx

## Ad Format Constraints

**Responsive Search Ads (RSA):**
- Headlines: 3–30 characters each, minimum 5 per ad
- Descriptions: up to 90 characters each, minimum 2 per ad
- Minimum 2 ad variations per campaign
- Google assembles the best combination from your headlines and descriptions

**Sitelink Extensions:**
- Link text: up to 25 characters (the clickable blue text)
- Description line 1: up to 35 characters
- Description line 2: up to 35 characters
- Final URL: must be distinct from the main ad landing URL and from all other sitelink URLs
- Minimum 2 sitelinks per campaign (Google rarely shows just 1)
- Maximum 4 sitelinks for Phase 1 (balances coverage vs complexity at $250 budget)
- Each sitelink must point to a different destination page or anchor section
- Auto-generated from `golden_path` pages — see state-4-generate.md Step 4b.5

## Targeting Model

**Keyword-based targeting** — ads appear when users search for matching terms.

Match types:
- **Exact match** `[keyword]` — highest intent, most specific
- **Phrase match** `"keyword"` — moderate intent, word order matters
- **Broad match** `keyword` — widest reach, Google infers intent
- **Negative keywords** — exclude irrelevant searches

Minimum keyword counts:
- Exact: 3+
- Phrase: 2+
- Broad: 1+
- Negative: 2+

No demographic or audience targeting initially — let Google optimize.

## Click ID

**Parameter name:** `gclid` (Google Click ID)

Google auto-appends `gclid` to the landing URL when a user clicks an ad. Capture it on the landing page and include it in analytics events for offline conversion matching.

## Conversion Tracking

Offline conversion import (PostHog -> Google Ads) is a Phase 3 smart-bidding setup step only.

Phase 1 and Phase 2 use Manual CPC and compute GO/NO_GO from PostHog/DB plus Google Ads clicks (`signup` or `pay_intent` divided by paid clicks). They do not create Google Ads conversion actions and do not import conversions.

When you move to Phase 3 smart bidding, configure the analytics provider's Google Ads destination, map the target event to the Google Ads conversion action, and use the provider webhook -> Google Ads Offline Conversions import method.

## Policy Restrictions

**Restricted industries:**
- **DeFi protocols, ICOs, token sales** — **BANNED**. Google Ads prohibits advertising decentralized finance protocols, initial coin offerings, and token sale events.
- **Crypto exchanges/wallets** — **RESTRICTED**. Requires FinCEN MSB registration + state money transmitter licenses (US) or MiCA CASP authorization (EU). Must apply for Google Ads Financial Products certification.
- **Gambling, pharma, weapons** — various restrictions apply; check Google Ads policies.

**Compliance notes:**
- Landing page must include clear disclaimers if promoting financial products
- Ads cannot make misleading claims about returns or guarantees
- Review [Google Ads Financial Products and Services policy](https://support.google.com/adspolicy/answer/2464998) before launching

## Cost Model

**CPC (Cost Per Click)** — you pay when a user clicks your ad.

Use `manual_cpc` for Phase 1 and Phase 2 screens. Bidding has two separate knobs:
`budget.initial_max_cpc_cents` is the starting bid, and `guardrails.max_cpc_cents`
is the hard CPC ceiling.

Smart bidding (`maximize_conversions` / `target_cpa`) is a Phase 3 scaling concern and is not used in the Phase 1 screen.

- Phase 1 starts at 140 cents ($1.40) and may raise stepwise toward the 250 cent ($2.50) ceiling only when volume is short. Phase 2 uses the same defaults unless Phase 1's actual average CPC exceeded $1.40; in that case Phase 2 may start at the proven Phase 1 average CPC, still never above the ceiling.
- Keyword Planner "Top of page bid (low range)" is the pre-flight affordability reference, not the initial-bid rule. If the keyword set's low-range average is above $2.50, make a day-0 affordability call before launching.

Budget structure:
- `click_target`: paid-click stop condition A. Phase 1 default 100; Phase 2 default 300.
- `total_budget_cents`: hard MAX cap, not a spend target. It is derived as `click_target x guardrails.max_cpc_cents` (100 x 250 cents = 25000 cents / $250; 300 x 250 cents = 75000 cents / $750). Hitting it before the click target is the affordability signal.
- **Premium-price escalation (Team Lead only):** for products priced > $50/mo where $2.50 cannot buy volume (day-0: Keyword Planner low range above the ceiling; or mid-flight: the bid ladder is exhausted at $2.50 with no impressions), the Team Lead may approve a raise using `approved ceiling ≈ monthly price × 5%` (= 0.6 safety × 1.5% click→paid × 5-month LTV × 0.9 margin; the uniform $2.50 ≈ a $50/mo product). The identities still hold: `new cap = click target × new ceiling`, `new daily = new cap ÷ duration_days`. Example: $99/mo → ceiling $5.00 → Phase 1 $500 cap / $70 per day; Phase 2 $1,500 cap / $71 per day. Record the approval in ads.yaml as `budget.cap_override_approved_by` (the validator requires it above $750 and enforces an absolute $2,000 bound). Click targets and durations never change. Day-0 (before launch): tell `/distribute` the approved numbers when it generates ads.yaml — `state-4-generate.md:176` is the contract: "These are defaults — if experiment.yaml or user input specifies different values, those take precedence." The whole `/distribute` chain reads ads.yaml values, so approved numbers flow through with zero skill changes. Mid-flight (ladder exhausted at $2.50): update ads.yaml with the approved bundle (ceiling/cap/daily + `cap_override_approved_by`), commit via a PR titled "...cap raise approved by <name>", run `make distribute` to validate, then raise keyword bids in the Google Ads UI toward the new ceiling and, if needed, the daily budget. Monitoring needs no reconfiguration — `/iterate --check` reads the raised numbers from ads.yaml. When approving, have the member show you the committed ads.yaml diff (the PR title names the approval); the validator requires the field and prints CAP OVERRIDE ACTIVE on every run.
- `daily_budget_cents`: pacing default, 2000 cents ($20/day) for both phases. Raise it only to compress calendar time; it is not a guardrail.
- `duration_days`: nominal window, written into Google Ads as the campaign End date. Phase 1 is 7 days because `100 / ($20 / $1.40 ~= 14.3 clicks/day) ~= 7`; Phase 2 is 21 days because `300 / 14.3 ~= 21`. If the End date arrives with clicks below target and spend below cap, extend the End date manually.

Fail-safe: if the operator forgets everything, Google Ads stops the campaign at its End date after at most `daily_budget_cents x duration_days` ($140 in Phase 1, $420 in Phase 2), which is below the total cap by construction. Stop conditions are verdict-level: clicks >= target -> pause + report to the Team Lead (who runs the `/iterate --cross` verdict); spend >= cap -> pause + report and treat short-clicks as an affordability signal; bid at the ceiling with ~0 impressions (or $0 spend) for 7 consecutive days -> pause + report a bid-capped shortfall (never extend a $0-spend campaign — `/iterate --cross` flags these as stalled and forces a raise/relaunch/kill decision).

## Config Schema

The `ads.yaml` file for Google Ads uses:

```yaml
channel: google-ads
campaign_name: {name}-search-v{N}
project_name: {name}
landing_url: {deployed_url}
phase: 1                      # 1 or 2 — which screen this campaign belongs to; /distribute writes 1, the Phase 2 Playbook §5 prompt rewrites to 2. /iterate --check reads this FIRST (before the transient distribute context)
campaign_created_at: ...      # YYYY-MM-DD — campaign age source for /iterate --check
dayzero_probe_passed_at: ...  # YYYY-MM-DD — Phase 2 day-0 relay probe PASS date; REQUIRED when phase: 2 (check 38 fails without it, /iterate --check STOPs); written by the Phase 2 Playbook §5 step 11 prompt

keywords:
  exact: [...]
  phrase: [...]
  broad: [...]
  negative: [...]

ads:
  - headlines: [...]    # 5+ headlines, 3-30 chars each
    descriptions: [...]  # 2+ descriptions, up to 90 chars each

# When experiment.yaml has variants, use ad_groups instead of ads:
# ad_groups:
#   - variant: {slug}
#     landing_url: "{url}/v/{slug}?utm_source=google&utm_medium=cpc&utm_campaign={campaign}&utm_content={slug}"
#     ads:
#       - headlines: [...]
#         descriptions: [...]

sitelinks:
  - link_text: "..."            # up to 25 chars, imperative verb + noun
    description_1: "..."        # up to 35 chars, benefit statement
    description_2: "..."        # up to 35 chars, qualifier/differentiator
    final_url: "..."            # distinct URL with UTM params
# When <2 qualifying pages exist: sitelinks: []
# See state-4-generate.md Step 4b.5 for generation rules

budget:
  daily_budget_cents: ...      # pacing default; $20/day for Phase 1/2
  total_budget_cents: ...      # = click_target x guardrails.max_cpc_cents
  cap_override_approved_by: ...  # OPTIONAL — Team-Lead-approved premium-price raise (> $50/mo). Validator: REQUIRED whenever max_cpc_cents > 250 or total > 75000 (google-ads); with it, total may go to 200000 absolute and must equal click_target × max_cpc_cents
  duration_days: ...           # nominal window; set as campaign End date; extend manually
  click_target: ...            # stop condition A; Phase 1 default 100 = iterate-cross visitors_floor
  initial_max_cpc_cents: ...   # default starting bid; Phase 1/2 default 140
  bidding_strategy: manual_cpc

targeting:
  locations: [US]
  languages: [en]

conversions:
  primary_action: signup_complete
  secondary_actions: [activate]
  import_method: posthog_webhook

# Phase 3 conversion-action reference only. Phase 1/2 do not import conversions.

guardrails:
  max_cpc_cents: ...           # CPC CEILING (= total_budget_cents / click_target); never bid above
  min_daily_clicks: 3
  auto_pause_rules: [...]

thresholds:
  expected_clicks: ...
  expected_signups: ...
  expected_activations: ...
  go_signal: "..."
  no_go_signal: "..."
```

## Phase 1 Playbook

Step-by-step guide for the first 7 days of a Google Ads Search campaign. Follow this before adjusting any settings.
`/distribute` will not create the campaign unless `/ads-ready phase-1` passes against the current deploy.

### Who Does What

| Role | Responsibilities |
|------|-----------------|
| **You (MVP owner)** | Get the app ads-ready, launch via `/distribute`, run `/iterate --check` once a day, pause/extend the campaign when a stop condition fires, report results to your Team Lead — and tell your Team Lead **the same day** whenever the campaign enters ANY non-active state (paused / ended / removed), for any reason, not only when a stop condition fires |
| **Team Lead** | Runs `/iterate --cross` periodically across ALL MVPs and announces each verdict (GO / NO_GO / keep running). **You never run `/iterate --cross` yourself** |

### Quick Guide (read this first — no marketing experience needed)

The whole of Phase 1 in one sentence: **we pay Google to send visitors to your landing page, and count how many sign up.** Everything below is detail; the tools make the decisions.

1. **Get ready.** Run `/ads-ready phase-1`. Fix what it reports, re-run until it passes.
2. **Launch.** Run `/distribute`. It generates the ad copy and settings, creates the campaign in Google Ads (PAUSED), and walks you through the pre-flight checklist. All settings are standardized — you do not have to make any marketing decisions.

**During the screen, do not run any other promotion channel (Reddit/HN/newsletter/etc.). The verdict assumes every signup came from the ads — other traffic inflates the conversion rate and can produce a false GO.**

3. **Wait for ad review.** Google reviews new ads for 24–48h. Run `/iterate --check` the next day; once ads are approved it unpauses the campaign automatically.
4. **Check once a day.** Run `/iterate --check` daily. It reads clicks/spend/health, auto-fixes common issues, and tells you when to act.
5. **Stop when one of four things happens:**
   - **100 paid clicks reached** → pause the campaign, tell your Team Lead. (Success — we have enough data.)
   - **$250 total spent** → pause the campaign, tell your Team Lead. (Clicks were too expensive — that is itself a useful result. **Exception:** if your product is priced > $50/mo, tell your Team Lead — they can approve a higher ceiling and budget instead of stopping.)
   - **Bids at the $2.50 ceiling and still ~0 impressions (or $0 spent) for 7 days in a row** → pause the campaign, tell your Team Lead it is a **bid-capped shortfall**. (Your ad never enters the auction — the market charges more than $2.50 per click for these keywords. Waiting will not produce data; your Team Lead decides: approved higher ceiling, different keywords, or write the channel off.)
   - **End date arrives with none of the above** → extend the End date in Google Ads by `(250 − spent) ÷ 20` days and keep going — **only if you have spent more than $0**. A campaign with zero spend is stalled, not slow: that is the bid-capped shortfall above, never an extension.
6. **Get the verdict.** Your Team Lead compares all MVPs and tells you: GO (prepare for Phase 2), NO_GO (stop, write a `/retro`), or keep running.

### Jargon Decoder

| Term | Meaning |
|------|---------|
| CPC | Cost per click — what you pay Google when someone clicks your ad |
| Impression | Your ad was shown once on a results page (shown ≠ clicked) |
| CTR | Click-through rate = clicks ÷ impressions |
| Max CPC (bid) | The most you are willing to pay for one click. We start at $1.40 and never go above $2.50 |
| Phrase Match | Your ad shows only on searches containing your phrase. Precise, lower volume |
| Broad Match | Google loosely matches related searches. More volume, less precise — last resort |
| RSA | Responsive Search Ad — you supply headlines + descriptions, Google mixes and tests combinations |
| STAG | Single Theme Ad Group — all keywords in the group share one theme |
| Negative keyword | A word that BLOCKS your ad from showing (e.g. "free", "jobs") so you don't pay for useless clicks |
| gclid / UTM | Tracking tags on the landing URL that let us attribute each signup back to the ad click |
| End date | The campaign's built-in off switch — if everyone forgets everything, spending stops there |

### Campaign Structure

| Setting | Value |
|---------|-------|
| Campaign type | Search |
| Network | Google Search only (disable Search Partners and Display Network) |
| Bidding | `manual_cpc` (Enhanced CPC OFF) |
| Max CPC | $1.40 initial (`budget.initial_max_cpc_cents`); raise stepwise on volume shortfall only, never above the $2.50 ceiling (`guardrails.max_cpc_cents`) |
| Daily budget | $20/day default (`daily_budget_cents`; raise only to compress calendar time) |
| Duration | 7 days nominal -- set as the campaign End date; extend manually when neither stop condition is met |
| Status | PAUSED (enable after pre-flight checklist passes) |

Goal & stopping rule: stop A is clicks >= 100 -> pause + report to your Team Lead (the lead runs `/iterate --cross` for the verdict); stop B is spend >= the $250 cap -> pause + report — clicks came in too expensive, which is itself a signal (affordability); stop C is bid at the $2.50 ceiling with ~0 impressions (or $0 spend) for 7 consecutive days -> pause + report **bid-capped shortfall** to your Team Lead — the ceiling is below the market's first-page minimum, so waiting buys nothing (the day-0 twin of this check is pre-flight item 10; the Team Lead resolves it via the premium-price escalation above, a keyword/channel swap, or a channel-infeasible call in `/iterate --cross`). If the End date is reached with none of the three met, extend manually using headroom `(cap - spent) / $20` days — **only when spend > 0**; never extend a $0-spend campaign (that is stop C, not slowness).

### Ad Group Structure

- **1 STAG** (Single Theme Ad Group) per campaign
- **5-15 keywords** per ad group, all on the same theme
- **Match type**: Phrase Match for all keywords. If a keyword gets zero impressions, first raise that keyword's bid stepwise toward, and capped at, the $2.50 ceiling (`/iterate --check` automates this as `min(top-of-page high range, ceiling)`). If it still has zero impressions ~24h after the raise (campaign age 48-72h), switch that keyword to Broad Match. Bid raises preserve sample composition; Broad Match changes it.
- **2 RSAs** (Responsive Search Ads) per ad group

### RSA Template

```
Headlines (8 slots):
  H1: [MVP Name] — PINNED to position 1
  H2: [Primary value proposition] — PINNED to position 2
  H3-H8: Unpinned — rotate variations of benefits, features, social proof, urgency

Descriptions (4 slots):
  D1: [What the product does + primary benefit] (up to 90 chars)
  D2: [How it works or what makes it different] (up to 90 chars)
  D3: [Social proof or credibility signal] (up to 90 chars)
  D4: [Call to action with urgency] (up to 90 chars)
```

Pin H1 and H2 to ensure the MVP name and value prop always appear. Leave H3-H8 unpinned so Google can test combinations.

### Negative Keywords (Universal)

Add these 50 universal negative keywords to every campaign. They exclude traffic that wastes budget on informational, career, enterprise, or unrelated searches.

```
free
how to
what is
tutorial
guide
example
template
sample
course
training
certification
degree
salary
job
jobs
career
careers
hiring
intern
internship
enterprise
corporate
fortune 500
government
federal
download
open source
github
stackoverflow
reddit
review
reviews
comparison
vs
versus
alternative
alternatives
cheap
cheapest
discount
coupon
promo
scam
complaint
lawsuit
wiki
wikipedia
definition
meaning
pdf
```

These are starting negatives. Add campaign-specific negatives based on the experiment domain (e.g., competitor names that draw irrelevant clicks).

### Sitelink Strategy

- **Auto-generate** sitelinks from experiment.yaml `golden_path` when the app has 2+ non-landing user-facing pages
- **Priority order**: real independent pages (signup, dashboard, etc.) > anchor sections on the landing page (`/#features`, `/#pricing`) > skip
- **Anchor fallback**: When independent pages < 2, scan the landing page component for section elements with `id` attributes (e.g., `id="features"`, `id="pricing"`) and generate anchor sitelinks
- **Combined threshold**: independent pages + anchor sections must total >= 2, otherwise skip sitelinks entirely
- **Phase 1 cap**: maximum 4 sitelinks
- **Copy rules**: follow messaging.md Section F for link_text, description_1, description_2 derivation
- **UTM tracking**: each sitelink URL includes `utm_content=sitelink_{route_slug}` (or `sitelink_anchor_{section_id}` for anchors)

### Pre-flight Checklist

Before enabling the campaign.

**Covered by `/ads-ready` — do NOT re-check by hand:**
- **App-side tracking** (gclid capture on the landing page, events firing, analytics wiring) — proven by `/ads-ready`'s live smoke, a scripted Playwright + PostHog API check (deterministic, and it fails closed: an event either arrived or it didn't). Phase 1: `/distribute` refuses to create the campaign without a fresh pass (same git HEAD, smoke not skipped). Phase 2: §4 requires `/ads-ready phase-2`, whose base checks are a superset of phase-1.

**A. Campaign settings — double-check in the Google Ads UI (~30 seconds):**

In Phase 1 `/distribute` sets and audits these automatically, but that audit is UI automation and can mis-read — a quick manual pass is cheap insurance. In Phase 2 you created the campaign by hand, so this is the only verification.

1. [ ] Campaign status is PAUSED
2. [ ] Bidding is Manual CPC (Enhanced CPC OFF), default max CPC = $1.40
3. [ ] Daily budget = $20/day
4. [ ] End date = start date + `duration_days`
5. [ ] Negative keywords added (50 universal + campaign-specific)
6. [ ] Networks: Google Search only (Search Partners OFF, Display OFF)

**B. Everything else (both phases):**

7. [ ] Landing page PageSpeed score >= 70 (mobile)
8. [ ] All ads approved by Google (check ad status — allow 48 hours for review)
9. [ ] UTM parameters set correctly on all final URLs (`utm_campaign` must match the campaign name) — and every ad Final URL AND sitelink URL points at THIS MVP's deployed domain. A URL pasted from another MVP silently spends your budget on someone else's traffic (clicks that can never convert for you); `/iterate --cross` only flags it as a foreign-campaign leak after the money is gone.
10. [ ] Keyword Planner top-of-page bid (low range) average for the keyword set <= $2.50 (the CPC ceiling); otherwise make a day-0 affordability call: NO_GO — or, if your product is priced > $50/mo, ask your Team Lead for an approved raise (see Cost Model: the approved ceiling/cap/daily replace $2.50/$250-$750/$20 everywhere in this playbook for that MVP; click targets 100/300 never change).
11. [ ] Recommended, ADVISORY Automated Rules configured with the longest date range available (All time if offered): `cost >= total cap -> pause`; `clicks >= click_target -> pause`. Rule windows are bounded, so the binding mechanisms remain the End date plus `/iterate --check`; a previous-30-days window at $20/day tops out around $600 / 240 clicks and cannot observe Phase 2's $750 / 300 lifetime totals.

### Phase 1 Monitoring (daily until a stop condition fires)

**Re-run `/ads-ready` after ANY deploy while a campaign is active** — the launch gate only proved the deploy that existed at launch.

| Metric | Check frequency | Action threshold |
|--------|----------------|-----------------|
| Paid clicks vs target (100) | Daily | clicks >= 100 -> pause + report to your Team Lead (lead runs `/iterate --cross`) |
| Total spend vs $250 cap | Daily | spend >= cap -> pause + report; if clicks < 100, the traffic was too expensive (affordability NO_GO signal) |
| End date | At end date | no stop condition met AND spend > 0 AND spend < cap -> extend End date (headroom = (cap - spent) / $20 days); $0 spend -> never extend, that is a bid-capped shortfall |
| Impressions | Daily | < 50/day after day 2 -> raise bids first (capped at the $2.50 ceiling); still zero ~24h after the raise -> switch that keyword to Broad Match |
| Bid-capped shortfall | Daily | at the $2.50 ceiling AND ~0 impressions (or $0 spend) for 7 consecutive days -> pause + report "bid-capped shortfall" to your Team Lead (do NOT extend the End date; resolution = premium-price escalation, keyword/channel swap, or channel-infeasible call) |
| CTR | Daily | < 1% after 500 impressions → revise ad copy |
| Avg CPC | Daily | approaching the $2.50 ceiling without enough volume -> finish the ladder, then consider affordability NO_GO |
| Signups | Day 4+ | 0 signups after 50% budget spent → verify tracking, check landing page |
| Search terms report | Day 3, Day 7 | Add irrelevant terms to negative keywords |
| Tracking capture rate | Daily (via /iterate --check) | capture < 50% -> re-run /ads-ready against the current deploy; fix before trusting any verdict |

## Phase 2 Playbook (Value Screen)

> **Sibling of the Phase 1 Playbook.** Phase 1 screened for **demand** (signup). Phase 2 screens for **value** (will they pay). Inherits everything not restated here (account structure, gclid capture, UTM scheme, RSA format, negative keywords, the Jargon Decoder). **Phase 2 is run manually — not via `/distribute`.**

### Quick Guide (read this first)

Phase 1 asked "do people want it?" (signups). Phase 2 asks "**will they pay?**" — we show a fake "Upgrade to Pro · $X/mo" button to people who actually used the product, and count who clicks it. **Nobody is ever charged.**

1. **Wait to be picked.** Your Team Lead announces which Phase-1 GO MVPs enter Phase 2.
2. **Build the fake door.** Copy-paste the `/change` brief from §3. The ONLY thing you change is the price — use YOUR product's real intended price.
3. **Check the wiring.** Run `/ads-ready phase-2` until it passes.
4. **Create the campaign by hand** following the numbered steps in §5 (Phase 2 campaign creation is not automated). Run the 2-minute day-0 probe (§5 step 10) — it proves the tracking relay end-to-end before money flows. Then don't skip §5 step 11 — the copy-paste prompt that points `/iterate --check` at your new Phase 2 campaign and records the probe PASS date (`make distribute` fails phase-2 configs without it).

**During the screen, do not run any other promotion channel (Reddit/HN/newsletter/etc.). The verdict assumes every pay-intent came from Phase 2 ad traffic — the utm filter protects the numerator, but mixed campaigns still pollute capture-rate diagnostics and the Phase-1-style signup comparisons.**

5. **Check once a day** with `/iterate --check`. Stop rules: **300 paid clicks** or **$750 total spent** → pause + tell your Team Lead (priced > $50/mo? the lead can approve a raise instead of stopping). End date (21 days) arrives with neither → extend by `(750 − spent) ÷ 20` days. If the campaign goes non-active for ANY other reason (you paused it, Google paused it, it ended, it was removed), tell your Team Lead **the same day** — a silently stopped Phase 2 campaign freezes its verdict as INSUFFICIENT_DATA forever.
6. **Get the verdict from your lead** (`/iterate --cross --phase2`): GO = candidate for Phase 3 (real payment goes in), NO_GO = people used it free but won't pay, keep-running = not enough clicks yet.

### 0. What Phase 2 is — and is NOT
A screen, not a scale-up. It tests whether Phase 1 signups are real value or vanity, by measuring willingness to pay. Only **Phase 3** is the long-term commit. Phase 2's job: decide which winners earn a scarce Phase 3 slot. It measures one thing: **of the people we paid to bring, how many take a money-shaped action.**

### 1. Entry
Run on an MVP only when: Phase 1 verdict = **GO** (`/iterate --cross`), and Phase 1 tracking was healthy (no `MISSING_PROJECT_NAME`/`GA_NO_PH_TRACKING`/attribution flags).

### 2. The numbers you set (STANDARDIZED: θ₂, budget cap, duration · PER-MVP: reference price)
Reference price = each MVP's own real intended price (a simple tool and a complex product should not share one price). Standardized Phase 2 numbers:

- The reference price is **FROZEN for the entire Phase 2 run** — every pay_intent must answer the same offer, and the cross ranking multiplies your rate by this price. Changing $X mid-run corrupts the blended rate (the verdict flags it as `price_change_mid_phase`). If you must change it: tell your Team Lead, close the campaign, and start `v{N+1}` with a fresh count — old clicks and pay-intents do not carry over.
- `θ₂ = 0.02` is the pay-intent rate GO gate.
- Click target and floor: 300 paid clicks (`pay_intent_visitors_floor`). This gives the same evidence mass as Phase 1: 300 x 2% = 6 expected pay-intents, matching Phase 1's 100 x 6% = 6 expected signups.
- Total MAX cap: $750 (75000 cents) = 300 clicks x the $2.50 CPC ceiling. This is the affordability bound, not a spend target.
- Priced > $50/mo and the $2.50 ceiling can't buy volume? Ask your Team Lead for an approved raise (Cost Model: Premium-price escalation). The 300-click target never changes.
- Daily budget: $20/day default. Raise only to compress calendar time.
- Nominal duration: 21 days, because 300 / ($20 / $1.40 ~= 14.3 clicks/day) ~= 21. Set this as the Google Ads End date.
- Bids: $1.40 initial with the same ladder to the $2.50 ceiling. You may start at Phase 1's actual average CPC when it exceeded $1.40 because Phase 1 already proved that price buys this keyword set's volume.
- Stop rule: clicks >= 300 OR spend >= $750. If the End date arrives with neither condition met, extend manually using headroom `(750 - spent) / 20` days.

### 3. Build the fake-door (per-MVP `/change` — see Appendix B brief)
User flow (uniform, signup-gated):
```
① Ad click → landing (/?gclid=…&utm_campaign=…) → capture gclid + utm_campaign (cookie/sessionStorage); fire visit_landing (reach)
② Sign up / log in  → fire signup_complete (demand); ★ persist gclid + utm_campaign onto the user record
③ Activate (use core feature once) → fire activate; ★ Upgrade CTA becomes visible only after this
④ Fake-door "Upgrade to Pro · $X/mo" (post-activation, logged-in; no real payment; $X is this MVP's real intended price)
⑤ Click → fire pay_intent (monetize){plan,price_cents,gclid,utm_campaign}; POST /api/pay-intent → row{user_id,distinct_id,gclid,utm_campaign,price_cents,created_at}; do NOT re-ask email
⑥ Honest confirmation: "You're on the Pro early-access list — we'll email you when it's live." (no charge → Google-Ads-safe)
```
Invariants: **gclid + utm_campaign relay** (landing→user→pay_intent event & row — both explicit, not the super-property); gate is **activate**, not login; reuse identity (never re-collect email).

Copy-paste `/change` brief:
```
/change Add a fake-door "Upgrade to Pro" value probe for Google Ads Phase 2. NO real payment.

Requirements (follow exactly — only the reference price differs per MVP; use this MVP's real intended price):
1. EVENTS.yaml: add event
     pay_intent:
       funnel_stage: monetize           # NOT requires:[payment] — fake door
       trigger: User clicks the fake-door Upgrade CTA (post-activation). No charge.
       properties:
         plan:         { type: string, required: true }
         price_cents:  { type: number, required: true }   # MVP's real intended price in cents, shown not charged
         gclid:        { type: string, required: false }
         utm_campaign: { type: string, required: true }   # REQUIRED — explicit phase attribution; required:true forces the wrapper signature + lets the static check assert the callsite passes it (R3/HIGH-3). Pass "" when no campaign.
   Add typed wrapper trackPayIntent({plan, price_cents, gclid, utm_campaign}) to events.ts.
2. DB: table `pay_intent` (id, user_id uuid REFERENCES auth.users(id), distinct_id, gclid, utm_campaign, price_cents, created_at) — follow the template's user-owned-table convention (Supabase: FK to `auth.users(id)`, NOT a `users` table; see `.claude/stacks/database/supabase.md`), RLS ENABLED, server-write only.
3. API POST /api/pay-intent: zod-validate, insert one row for the authenticated user incl. the gclid stored on their user record. Add a unit test.
4. UI: "Upgrade to Pro · $X/mo" CTA using this MVP's real intended price, visible only after login AND activation. On click: trackPayIntent({plan:"pro", price_cents:1900, gclid, utm_campaign}); POST /api/pay-intent; show "You're on the Pro early-access list — we'll email you when it's live." Do NOT open checkout, charge, or re-ask email. (1900 = $19 is only an example.)
5. Attribution relay (BOTH `gclid` AND `utm_campaign`): captured on landing → persisted on the user record at signup → read back onto the `pay_intent` event props AND DB row. Reuse the existing Phase-1 gclid capture path for `utm_campaign` too — do NOT rely on PostHog's `utm_campaign` super-property for the deep-funnel `pay_intent` event (it lacks gclid's hardened dual-capture; R2/HIGH-1).
Do not add Stripe or real payment. Do not change how the core feature is gated.
```

### 4. Pre-flight — `/ads-ready phase-2` must pass (STATIC config check)
`/ads-ready phase-2` is a **source-wiring** check, not a live behavioral test (the smoke harness has no authenticated-session driver). It statically verifies: `pay_intent` is defined in EVENTS.yaml (monetize, no `requires:[payment]`) with a called `trackPayIntent` wrapper; a `POST /api/pay-intent` route inserts a `pay_intent` row including `gclid` + `utm_campaign`; the migration references `auth.users(id)` with RLS; the Upgrade CTA is behind an activation render-guard; no payment-provider import is reachable from the fake-door path. It **cannot** prove runtime firing or catch a determined forgery — forgery-resistance comes from using the one canonical `/change` brief.
If run bare, `/ads-ready` asks whether to check Phase 1 or Phase 2; use `/ads-ready phase-2` here to keep the manual Phase 2 gate explicit.

### 5. Create the Phase 2 campaign (manual — no MCP)
Create a **new, separate** campaign — do not reuse the Phase 1 campaign (mixing its clicks would corrupt the measurement). Steps:

**Re-run `/ads-ready` after ANY deploy while a campaign is active** — the launch gate only proved the deploy that existed at launch.

1. New campaign -> **Search**. Name it **`{mvp}-search-phase2-v{N}`**, where `{mvp}` is EXACTLY your experiment.yaml `name` (= ads.yaml `project_name` = the PostHog `project_name`) — `make distribute` rejects any other prefix (check 39), and a mismatched prefix strands your paid clicks on an unattributed row in the cross verdict. The "phase2" token is required; it is how the verdict isolates Phase 2 traffic (`phase2.utm_campaign_like`, default `%phase2%`).
2. Networks: **Google Search only** (no Search Partners, no Display).
3. Daily budget **$20/day** (or your Team-Lead-approved numbers). **End date = start date + 21 days.**
4. Bidding: **Manual CPC**, Enhanced CPC OFF; initial bid **$1.40** (or your Team-Lead-approved numbers); never raise above the **$2.50** ceiling (or your Team-Lead-approved numbers).
5. Clone the Phase 1 ad group: same keywords, RSAs, and negative keywords.
6. **Set `utm_campaign` to the phase2 campaign name on ALL final URLs** — this is what lets `/iterate --cross --phase2` count only Phase 2 traffic. **Heads-up: Google auto-tagging only adds `gclid`, NOT `utm_*`** — the campaign name does not propagate on its own, so if you skip this, real paid clicks arrive in PostHog with a `gclid` but an empty `utm_campaign` and become invisible to the verdict (it reads `GA_NO_PH_TRACKING`). Don't hand-edit each ad's URL; set it **once** at the campaign level: Settings → **Additional settings** → **Campaign URL options** → **Final URL suffix**, then paste (the value is the same name from step 1 and MUST contain the `phase2` token):

    ```
    utm_source=google&utm_medium=cpc&utm_campaign={mvp}-search-phase2-v{N}
    ```
7. (Recommended, ADVISORY) two Automated Rules as backup stops: pause at cost >= $750 (or your Team-Lead-approved cap); pause at clicks >= 300 — longest date range available. They are backup only (a bounded rule window cannot see a >30-day run's lifetime totals); the End date plus daily `/iterate --check` are the binding stops.
8. Do NOT set up conversion import — not needed (we measure in PostHog/DB). **Pause the Phase 1 campaign while Phase 2 runs.**
9. Create the campaign in **PAUSED** status. Copy the campaign's dashboard URL from your browser.
10. **Run the day-0 relay probe before spending.**

    Walk the funnel once yourself at the deployed site with:

    `https://<your-app>/?gclid=probe-<YYYYMMDD>&utm_campaign=dayzero-probe`

    Sign up with a fresh test account, activate by using the core feature once, then click the "Upgrade to Pro" button. The values are deliberately non-polluting: `dayzero-probe` contains no "phase2" so it can never match the verdict filters, and a `probe-` gclid fails the paid-gclid pattern — your probe cannot count toward any verdict, in PostHog OR the DB.

    Paste this prompt into Claude Code:

    ```
    Verify my Phase 2 day-0 probe (the fake-door relay end to end).
    1. Query PostHog for my project's `pay_intent` events from the last hour. Confirm at least one
       event has properties utm_campaign = "dayzero-probe" AND gclid = "probe-<YYYYMMDD>".
    2. Query my Supabase `pay_intent` table for rows from the last hour. Confirm the matching row
       carries gclid, utm_campaign = "dayzero-probe", and my price_cents value.
    3. Confirm the same PostHog pay_intent event's properties.project_name equals my
       experiment.yaml `name` — a pay_intent missing project_name is partial tracking and is
       invisible to the cross verdict.
    4. Report PASS only if ALL of the above hold verbatim. On FAIL, diagnose where the relay dropped
       them (landing capture -> user record -> event props / DB row) and tell me what to fix. Do not
       delete anything.
    ```

    Relay PASS + the pre-flight checklist sections A/B -> enable. If the probe fails, fix before spending. **Note today's date** — step 11 records it in ads.yaml as `dayzero_probe_passed_at`, and `make distribute` refuses phase-2 configs without it.

    The probe values are excluded from every verdict input structurally (paid-gclid gates + the numerator queries' `dayzero-probe` exclusion). If your Team Lead customized `phase2.utm_campaign_like` beyond the default `%phase2%`, confirm with them that `dayzero-probe` does not match it before walking the funnel.
11. **Point the tooling at Phase 2** — without this step, `/iterate --check` keeps watching the old Phase 1 campaign with Phase 1 stop rules. Paste this prompt into Claude Code (fill the two blanks):

    ```
    Point /iterate --check at my Phase 2 campaign.

    Campaign name: <PASTE: {mvp}-search-phase2-v{N}>
    Campaign URL:  <PASTE: the campaign dashboard URL from your browser>

    1. Update experiment/ads.yaml in place — change ONLY these fields:
       - campaign_name: the name above
       - campaign_id: the campaignId=XXXXXXXXXX parameter from the URL above
       - campaign_url: the URL above
       - phase: 2
       - campaign_created_at: today (YYYY-MM-DD)
       - dayzero_probe_passed_at: "<the date the step-10 probe PASSed, YYYY-MM-DD, quoted>"
       - budget.click_target: 300
       - budget.total_budget_cents: 75000
       - budget.duration_days: 21
       (If your Team Lead approved a premium-price raise, use the APPROVED numbers instead of the defaults above — total_budget_cents = 300 × the approved ceiling in cents, daily_budget_cents = total ÷ 21 — AND also set: guardrails.max_cpc_cents to the approved ceiling, and budget.cap_override_approved_by: "<the name your Team Lead tells you when approving>".)
       Keep everything else (keywords, ads, sitelinks, targeting) unchanged; guardrails unchanged too — UNLESS your raise was approved (see above).
    2. Validate: run `make distribute` — it must print "looks good". Fix anything it reports.
    3. Commit on a feature branch and open a PR (never commit directly to main); merge after checks pass.
    ```

    After this, `/iterate --check` monitors the Phase 2 campaign with the 300-click / $750 stop rules. `make distribute` enforces the `{mvp}` name prefix (check 39), the `phase2` token, and the recorded probe date (check 38) — a phase-2 config missing any of them fails validation.
12. Run the pre-flight checklist (Phase 1's list applies; in this manual flow section A is your ONLY verification of the campaign settings — there is no `/distribute` audit — static wiring by `/ads-ready phase-2` (§4); runtime relay by the day-0 probe (step 10)) -> enable.

### 6. Read the verdict — `/iterate --cross --phase2` (your Team Lead runs this)
`pay_intent_rate = pay_intent / clicks` (DB/PostHog numerator, Phase-2 GA-click denominator).
The click floor is the click target: `pay_intent_visitors_floor` (default 300). `clicks < floor → INSUFFICIENT_DATA` · `rate ≥ θ₂ → GO` · `rate < θ₂ → NO_GO (vanity: used free, won't pay)`. Tracking-integrity verdicts take precedence (same as Phase 1). The report surfaces `revenue_intent_per_click` ($/click) next to the rate; θ₂ on the rate remains the GO gate.

### 7. Act
**GO** → eligible for Phase 3; rank GO MVPs by `revenue_intent_per_click` (= pay-intent rate x reference price), promote **top-N** as slots open; Phase 3's first step swaps the fake-door for real payment. A higher-priced MVP with a solid rate can outrank a cheap one; θ₂ stays the uniform GO gate because revenue/click is higher-variance on thin data and is the rank, not the gate. **NO_GO** → stop, document in `/retro`. **INSUFFICIENT** → keep running.

### 8. Pitfalls
Separate campaign (clean denominator) · phase2 token in campaign name **and** `utm_campaign` · no real charge / no Stripe · reuse logged-in identity (no double email) · CTA only post-activation · verify wiring via `/ads-ready phase-2` (static) + the day-0 probe (runtime relay, PASS date recorded in ads.yaml) · set each MVP's real price; θ₂ (the pay-intent RATE) is the uniform GO gate, and ranking is value-weighted (revenue per click) so price differences stay comparable · reference price frozen for the whole run — mid-run price change = tell your Team Lead, close the campaign, relaunch as `v{N+1}` with a fresh count · campaign left active status (paused/ended/removed) for ANY reason → tell your Team Lead the same day. Do not stop at the calendar: stop at clicks >= 300 or the $750 cap. The End date is a fail-safe to extend, not a verdict deadline.

## UTM Parameters

- `utm_source=google`
- `utm_medium=cpc`
- `utm_campaign={campaign_name}`
- `utm_content={variant_slug}` (when using variants)
- `utm_content=sitelink_{route_slug}` (for sitelink traffic to independent pages)
- `utm_content=sitelink_anchor_{section_id}` (for sitelink traffic to anchor sections)

## Setup Instructions

### One-Time MCC Setup
1. **Create Google Ads MCC** (Manager Account) — see `.claude/procedures/google-ads-setup.md` for details

### Per-Member Setup (one-time per team member)
1. **Create a subaccount** — in the MCC, click "+ New Google Ads account" → name it `{member-name}-ads`. Billing is inherited from the MCC — do not add a separate payment method
2. **Complete Advertiser Verification** — Google will prompt verification for the new account. Complete it once — all future MVPs under this account skip verification
3. **Save Customer ID** — note the account's Customer ID (digits only, no dashes) and save it to `~/.google-ads/customer-id`

### Per-Campaign Setup (do this for each MVP)
1. **Switch to the member's subaccount** — click the subaccount name in the MCC account list to enter it
2. **Phase 1/2:** verify gclid capture and UTM attribution only; do not create or import Google Ads conversions
3. **Phase 3 smart-bidding prep only:** create conversion actions, configure the analytics destination, and map events — see `.claude/procedures/google-ads-setup.md` Steps 6-7 for details

### Dashboard Filter

Filter analytics dashboard by `utm_source = "google"` to see paid traffic performance.

## Chrome MCP Campaign Creation

Campaign creation uses Chrome MCP to interact with the Google Ads web UI directly. No API credentials needed — the user just needs to be logged into Google Ads in Chrome.

### Prerequisites

1. **Claude in Chrome extension** installed and connected (see `.claude/patterns/chrome-mcp-setup-guide.md`)
2. **Google Ads account** — user is logged into their sub-account in Chrome
3. **Chrome tab** with Google Ads open

If any prerequisite is missing, `/distribute` state-6 will detect it and show the setup guide automatically.

### Conversion Action Setup

This is optional Phase 3 smart-bidding prep. Phase 1 and Phase 2 Manual CPC screens do not require a Google Ads conversion action, and `/distribute` skips this by default.

| Setting | Value |
|---------|-------|
| Name | `MVP Signup` |
| Category | Lead → Sign-up |
| Source | Import (Other data sources or CRMs → Track conversions from clicks) |
| Count | One (one conversion per click) |
| Value | Don't use a value |
| Window | 30 days |

**Per sub-account, not per campaign.** Each team member has one sub-account. All their MVP campaigns share this `MVP Signup` action. Google Ads attributes conversions to the correct campaign automatically via the gclid.

**Idempotent.** If you choose to prepare Phase 3 conversion tracking, check the conversions list first. If `MVP Signup` already exists, skip creation.

### Campaign Creation Flow (via Chrome MCP)

`/distribute` state-6 performs these steps in the Google Ads UI:

1. Click "+ New campaign" → "Create a campaign without a goal's guidance" → Search
2. Set campaign name, uncheck Search Partners and Display Network
3. Set locations from `target_geo`, budget from ads.yaml, Manual CPC bidding
4. Create ad group with keywords (Phrase Match)
5. Create 2 RSAs from ads.yaml creative config
6. Add negative keywords at campaign level
7. Save campaign in PAUSED status
8. Record `campaign_id` and `campaign_url` in ads.yaml
9. Capture product screenshots and upload as Image Assets (user approves before upload)
10. Create sitelink extensions from ads.yaml `sitelinks` array (if non-empty)

### Image Assets

Google Search ads support optional Image Assets displayed alongside the text ad. `/distribute` state-6 Step 7.5 automates this by screenshotting the deployed MVP landing page.

| Spec | Dimensions | Content |
|------|-----------|---------|
| Landscape | 1200×628 | Hero section (headline + visual) |
| Square | 1200×1200 | Product UI / feature showcase |

**Process:** Chrome MCP opens the deployed URL → waits for full load → dismisses overlays → takes screenshots → crops to spec via imagemagick → shows to user for approval → uploads to Google Ads campaign Assets.

**Quality requirements:** Page must be fully loaded (no skeletons/spinners). No cookie banners, chat widgets, or popups visible. Use light mode if the page supports dark/light toggle.

**User approval gate:** Screenshots are shown to the user before upload. User can approve, request a different page section, or skip entirely.

### Error Handling

If Chrome MCP fails at any step, the skill:
1. Screenshots the error state
2. Reports which step failed
3. Retries up to 2 times, then asks user to resolve the issue and re-run `/distribute`
