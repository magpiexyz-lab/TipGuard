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
# Distribution: Reddit Ads
> Used when `/distribute` is run with channel `reddit`
> Assumes: None — distribution stacks create no source code or packages; they generate config only

## Ad Format Constraints

**Promoted Posts:**
- Headline: up to 300 characters
- URL (link post) or text body (text post)
- Optional thumbnail/image: 1200×628px recommended
- Minimum 2 post variations per campaign

Promoted posts appear in the subreddit feed and home feed alongside organic content.

## Targeting Model

**Community-based targeting** — ads appear in specific subreddits or to users with matching interests.

Targeting options:
- **Subreddits** — target specific communities (e.g., r/cryptocurrency, r/webdev, r/SaaS)
- **Interest categories** — target Reddit's interest taxonomy (e.g., "Technology", "Business & Finance")
- **Custom audiences** — retargeting via Reddit Pixel

Minimum targeting:
- At least 2 subreddits OR 2 interest categories

## Click ID

**Parameter name:** `rdt_cid` (Reddit Click ID)

Reddit appends `rdt_cid` to the landing URL when a user clicks an ad. Capture it on the landing page and include it in analytics events for conversion attribution.

## Conversion Tracking

1. Install the Reddit Pixel on the landing page
2. Set up conversion events in Reddit Ads → Events Manager
3. Map the `signup_complete` event → Reddit conversion event
4. Verify with Reddit Pixel Helper browser extension

Import method: Reddit Pixel (client-side) or Conversions API (server-side).

## Policy Restrictions

**Crypto-friendly:**
- **Crypto exchanges/wallets** — **ALLOWED**. Reddit permits cryptocurrency exchange and wallet advertising.
- **DeFi protocols** — **ALLOWED** with disclaimers. Include appropriate risk disclosures.
- **Token sales/ICOs** — **ALLOWED** with disclaimers. Must clearly state risks and regulatory status.
- **NFTs** — **ALLOWED**.

**General restrictions:**
- Ads must include disclaimers for financial products ("not financial advice", risk statements)
- Landing page must match ad content
- No misleading claims about returns or guarantees
- Reddit community guidelines apply — ads that feel spammy or misleading get downvoted and reported
- Review [Reddit Advertising Policy](https://www.redditinc.com/policies/advertising-policy) before launching

## Cost Model

**CPM (Cost Per Mille) or CPC (Cost Per Click):**

- **CPM**: pay per 1000 impressions — default for awareness
- **CPC**: pay per click — better for conversion-focused campaigns
- Recommended for MVPs: **CPC** — only pay for clicks to your landing page

Budget structure:
- `daily_budget_cents`: daily spend cap
- `total_budget_cents`: total campaign cap
- `duration_days`: campaign length

Threshold calculation for CPM:
- impressions = budget / (CPM / 1000)
- clicks = impressions × estimated CTR

## Config Schema

The `ads.yaml` file for Reddit uses:

```yaml
channel: reddit
campaign_name: {name}-reddit-v{N}
project_name: {name}
landing_url: {deployed_url}

targeting:
  subreddits: [...]
  interest_categories: [...]
  locations: [US]
  languages: [en]

posts:
  - headline: "..."     # up to 300 chars
    url: "..."          # landing URL with UTM params
    thumbnail: "..."    # optional, 1200x628px image

# When experiment.yaml has variants, include utm_content in landing URLs:
# posts:
#   - headline: "..."
#     variant: {slug}
#     url: "{url}/v/{slug}?utm_source=reddit&utm_medium=paid_social&utm_campaign={campaign}&utm_content={slug}"

budget:
  daily_budget_cents: ...
  total_budget_cents: ...
  duration_days: ...
  bidding_strategy: cpc  # or cpm

conversions:
  primary_action: signup_complete
  secondary_actions: [activate]
  import_method: reddit_pixel

guardrails:
  max_cpc_cents: ...     # max cost per click (CPC) or omit for CPM
  auto_pause_rules: [...]

thresholds:
  expected_impressions: ...
  expected_clicks: ...
  expected_signups: ...
  expected_activations: ...
  go_signal: "..."
  no_go_signal: "..."
```

## UTM Parameters

- `utm_source=reddit`
- `utm_medium=paid_social`
- `utm_campaign={campaign_name}`
- `utm_content={variant_slug}` (when using variants)

## Setup Instructions

1. **Create Reddit Ads account** at [ads.reddit.com](https://ads.reddit.com)
2. **Add payment method** — credit card
3. **Install Reddit Pixel** on the landing page
4. **Create conversion event** — Events Manager → New Conversion → custom event
5. **Map events** — `signup_complete` event → Reddit conversion event
6. **Verify** — use Reddit Pixel Helper to confirm pixel is firing

### Dashboard Filter

Filter analytics dashboard by `utm_source = "reddit"` to see paid traffic performance.
