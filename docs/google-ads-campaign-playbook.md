# Google Ads Campaign Playbook

Last updated: April 13, 2026

---

## Quick Reference

| Setting | Phase 1 | Phase 2 |
|---------|---------|---------|
| Budget | $140 / 7 days ($20/day) | $500 / 14 days (~$35.71/day) |
| Bidding | Manual CPC | Manual CPC (Smart Bidding only if projected conversions > 30) |
| Match type | Phrase Match | Phrase Match |
| Network | Google Search only | Google Search only |
| Ad group | 1 STAG, 5-15 keywords | 1 STAG, 5-15 keywords |
| RSAs | 2 per ad group | 2 per ad group |
| Geo | US, GB, CA, AU, NZ (or `target_geo` override) | Same |
| Negative keywords | 30-50 universal exclusions | Same |
| **Conversion event** | **Signup only** | Signup + Activation |

---

## Prerequisites

Before running `/distribute phase-1`:

1. Claude Code installed and running
2. Claude-in-Chrome extension installed and connected
3. Logged into Google Ads in Chrome (your sub-account under the team MCC)
4. MVP deployed and live (`/deploy` completed)

If the Chrome extension is not set up, `/distribute` will detect this and show a setup guide.

---

## Workflow

### Step 1: Build and Deploy

```
/spec        # generates experiment.yaml
/bootstrap   # builds the MVP
/deploy      # deploys to production
```

### Step 2: Run Distribute

```
/distribute phase-1
```

The skill automatically:
- Checks ad-readiness (gclid capture, UTM params, event tracking)
- Fixes missing tracking code and creates a PR if needed
- Generates keywords, ad copy, sitelinks
- Captures product screenshots for image assets
- Creates the campaign in Google Ads via Chrome (PAUSED)
- Sets up "MVP Signup" conversion action

**You will be prompted to approve:**
- The generated `ads.yaml` config before PR creation
- Product screenshots before image upload (you can skip or re-capture)

### Step 3: Double-Check Campaign Settings

> **This is the most important step.** The `/distribute` skill automates campaign creation but occasionally misses settings. Always verify before enabling the campaign.

See the full checklist in the next section.

### Step 4: Wait 48 Hours

The campaign is created PAUSED. Google needs time to review ad content. Do not enable the campaign before approval.

### Step 5: Enable Campaign

After Google approves the ads (status changes from "Under Review"):
1. Go to your campaign in Google Ads
2. Change status from Paused to Enabled

### Step 6: Monitor (Days 1, 3, 5)

```
/iterate --check
```

This automatically:
- Checks campaign health (impressions, clicks, spend)
- Adds negative keywords if junk traffic detected
- Raises bids if zero impressions
- Uploads conversion data (gclid) to Google Ads

### Step 7: Campaign Ends (Day 7)

Wait for the Team Lead to run `/iterate --cross` for the cross-MVP ranking.

---

## Double-Check Checklist

Open your campaign in Google Ads and verify each item. Check the box only after you've confirmed it in the live dashboard.

### Campaign Settings

| # | Setting | Expected Value | Where to Check |
|---|---------|---------------|----------------|
| 1 | Campaign type | Search | Campaign overview |
| 2 | Bidding strategy | **Manual CPC** | Settings > Bidding |
| 3 | Enhanced CPC | **OFF** (unchecked) | Settings > Bidding > Enhanced CPC |
| 4 | Daily budget | **$20.00** | Settings > Budget |
| 5 | Networks | **Google Search only** (Search Partners OFF, Display Network OFF) | Settings > Networks |
| 6 | Locations | US, GB, CA, AU, NZ (or your `target_geo`) | Settings > Locations |
| 7 | Ad schedule | All day, every day | Settings > Ad schedule |
| 8 | Campaign status | **Paused** | Campaign list |

### Keywords & Ads

| # | Setting | Expected Value | Where to Check |
|---|---------|---------------|----------------|
| 9 | Keywords | All in **"phrase match"** (shown with quotes) | Ad group > Keywords |
| 10 | Keyword count | 5-15 keywords | Ad group > Keywords |
| 11 | Negative keywords | 30-50 terms present | Campaign > Negative keywords |
| 12 | RSA count | **2** responsive search ads | Ad group > Ads |
| 13 | RSA Headline 1 | **Pinned** to MVP name | Click each RSA > check pin icon on H1 |
| 14 | RSA Headline 2 | **Pinned** to value proposition | Click each RSA > check pin icon on H2 |

### Conversion Tracking

Phase 1 only tracks **Signup** as the conversion event in Google Ads. Activation and purchase are tracked in PostHog but are NOT sent to Google Ads in Phase 1 (too few data points to be useful with $140 budget). The gclid import flow (`/iterate --check`) queries PostHog for users who clicked an ad (have gclid) AND completed signup (`funnel_stage: demand`), then uploads those as "MVP Signup" conversions.

| # | Setting | Expected Value | Where to Check |
|---|---------|---------------|----------------|
| 15 | Conversion action | **"MVP Signup"** exists (and is the only active conversion) | Tools > Conversions |
| 16 | Conversion source | **Import** (not website tag) | Tools > Conversions > MVP Signup |
| 17 | Conversion count | **One per click** | Tools > Conversions > MVP Signup |
| 18 | Conversion category | **Lead > Sign-up** | Tools > Conversions > MVP Signup |
| 19 | Sitelinks | 2-4 sitelinks (if generated) | Campaign > Assets > Sitelinks |
| 20 | Image assets | 2 images uploaded (if approved) | Campaign > Assets > Images |

### Code-Side Tracking (verify once)

Open your deployed MVP in a browser and check:

| # | Check | How to Verify |
|---|-------|--------------|
| 21 | gclid capture | Visit `your-url.com/?gclid=test123`, open PostHog, check `visit_landing` event has `gclid: test123`. **Note**: keep the test gclid under 30 chars — `/iterate --cross` filters out short gclids from cross-MVP analytics so this manual check never pollutes verdicts. See `.claude/patterns/iterate-cross-debug-prompts.md` for the full convention. |
| 22 | UTM capture | Visit `your-url.com/?utm_source=google&utm_medium=cpc`, check event has UTM properties |
| 23 | Signup event fires | Complete signup flow, check `signup_complete` event fires in PostHog with `funnel_stage: demand` |
| 24 | gclid-to-signup link | Do #21 and #23 in one session -- verify the same `distinct_id` appears on both events (this is how `/iterate --check` joins them for gclid import) |

### Common Issues `/distribute` Misses

| Issue | Symptom | Fix |
|-------|---------|-----|
| Enhanced CPC turned ON | Google auto-enables it | Settings > Bidding > uncheck "Enhanced CPC" |
| Search Partners enabled | Extra checkbox left on | Settings > Networks > uncheck "Search Partners" |
| Display Network enabled | Extra checkbox left on | Settings > Networks > uncheck "Display Network" |
| Keywords not in phrase match | Keywords shown without quotes | Edit each keyword, wrap in quotes |
| Missing negative keywords | Count < 30 | Campaign > Negative keywords > add from `ads.yaml` |
| Campaign not paused | Shows "Eligible" or "Enabled" | Pause immediately, wait for ad review |
| "MVP Signup" conversion missing | Tools > Conversions has no entry | Create manually: Import > Lead > Sign-up, count=One, window=30 days |
| Conversion source = Website tag | Google auto-added a tag-based action | Delete it, keep only the Import-based "MVP Signup" |

---

## Evaluation

After all campaigns finish (Day 7), the Team Lead runs `/iterate --cross`.

### Hard Elimination Rules (automatic)

| Condition | Result |
|-----------|--------|
| Zero impressions after all fallback measures | Eliminated |
| 50+ clicks but zero conversions | Eliminated |
| CTR below 1% for the full run | Eliminated |
| 3+ conversions | Automatically passes |

### Traction Score (Phase 1)

| Signal | Weight |
|--------|--------|
| Conversion Rate (ad visitors who signed up) | 45% |
| Relative CTR (vs industry average) | 25% |
| Cost Efficiency (cost per signup) | 20% |
| Quality Score | 10% |

### Score Thresholds

| Score | Verdict | Action |
|-------|---------|--------|
| Above 65 | **GO** | Advance to Phase 2 |
| 45 - 65 | **CONDITIONAL** | Extend testing or qualitative review |
| Below 45 | **NO-GO** | Pivot or drop |

---

## Phase Overview

| | Phase 1: Screening | Phase 2: Validation | Phase 3: Scale |
|-|--------------------|--------------------|----------------|
| Budget | $140 / 7 days | $500 / 14 days | $1,000+ / ongoing |
| Bidding | Manual CPC | Manual CPC (or Smart if >30 conversions) | Target CPA |
| Goal | Does anyone want this? | Which MVPs have product-market fit? | Can this make money? |
| Key metric | Conversion Rate | + Activation Rate | + Monetization, ROAS, Retention |
| Channels | Google Search | Google Search | Google + Meta + X |
