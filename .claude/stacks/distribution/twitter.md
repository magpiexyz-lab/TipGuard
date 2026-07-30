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
# Distribution: Twitter/X Ads
> Used when `/distribute` is run with channel `twitter`
> Assumes: None — distribution stacks create no source code or packages; they generate config only

## Ad Format Constraints

**Promoted Tweets:**
- Tweet text: up to 280 characters
- Minimum 2 tweet variations per campaign

**Optional Website Card:**
- Card title: up to 70 characters
- Card description: up to 200 characters
- Image: 800×418px (1.91:1) or 800×800px (1:1), max 5MB

When using Website Cards, the tweet text + card together form the ad creative.

## Targeting Model

**Interest and audience-based targeting** — ads appear in timelines of users matching your criteria.

Targeting options:
- **Interests** — select from Twitter's interest taxonomy (e.g., "Technology", "Cryptocurrency", "Finance")
- **Follower lookalikes** — target users similar to followers of specific handles (e.g., `@competitor1`, `@industry_leader`)
- **Timeline keywords** — target users who recently tweeted or engaged with specific keywords
- **Conversation topics** — target based on Twitter's conversation topics

Minimum targeting:
- At least 2 interests OR 2 follower lookalike handles OR 2 timeline keywords

## Click ID

**Parameter name:** `twclid` (Twitter Click ID)

Twitter auto-appends `twclid` to the landing URL when a user clicks an ad. Capture it on the landing page and include it in analytics events for conversion attribution.

## Conversion Tracking

1. Install the Twitter pixel (or use server-side conversion API)
2. Set up a Website Tag in Twitter Ads → Events Manager
3. Map the `signup_complete` event → Twitter conversion event
4. Verify with a test conversion

Import method: Twitter Pixel (client-side) or Conversions API (server-side).

## Policy Restrictions

**Crypto-friendly:**
- **Crypto exchanges/wallets** — **ALLOWED**. Twitter permits advertising cryptocurrency exchanges and wallet services.
- **DeFi protocols** — **ALLOWED**. Decentralized finance products can be advertised on Twitter.
- **Token sales/ICOs** — **ALLOWED** with disclaimers. Include risk disclosures where required by local law.
- **NFTs** — **ALLOWED**.

**General restrictions:**
- Ads must not make misleading claims about returns or guarantees
- Landing page must match ad content (no bait-and-switch)
- Financial disclaimers required where mandated by local regulations
- Review [Twitter Ads Policies](https://business.twitter.com/en/help/ads-policies.html) before launching

## Cost Model

**CPE (Cost Per Engagement) or CPM (Cost Per Mille/1000 impressions):**

- **CPE**: pay when a user engages (click, retweet, like, reply)
- **CPM**: pay per 1000 impressions — better for awareness campaigns
- Recommended for MVPs: **CPE** — only pay for actual engagement

Budget structure:
- `daily_budget_cents`: daily spend cap
- `total_budget_cents`: total campaign cap
- `duration_days`: campaign length

Threshold calculation for CPM:
- impressions = budget / (CPM / 1000)
- clicks = impressions × estimated CTR

## Config Schema

The `ads.yaml` file for Twitter uses:

```yaml
channel: twitter
campaign_name: {name}-twitter-v{N}
project_name: {name}
landing_url: {deployed_url}

targeting:
  interests: [...]
  follower_lookalikes: [...]   # @handles of competitors/leaders
  timeline_keywords: [...]
  locations: [US]
  languages: [en]

tweets:
  - text: "..."       # up to 280 chars
    card:              # optional
      title: "..."     # up to 70 chars
      description: "..." # up to 200 chars
      image: "..."     # URL or path to 800x418px image

# When experiment.yaml has variants, include utm_content in landing URLs:
# tweets:
#   - text: "..."
#     variant: {slug}
#     landing_url: "{url}/v/{slug}?utm_source=twitter&utm_medium=paid_social&utm_campaign={campaign}&utm_content={slug}"

budget:
  daily_budget_cents: ...
  total_budget_cents: ...
  duration_days: ...
  bidding_strategy: cpe  # or cpm

conversions:
  primary_action: signup_complete
  secondary_actions: [activate]
  import_method: twitter_pixel

guardrails:
  max_cpe_cents: ...     # max cost per engagement
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

- `utm_source=twitter`
- `utm_medium=paid_social`
- `utm_campaign={campaign_name}`
- `utm_content={variant_slug}` (when using variants)

## Setup Instructions

1. **Create Twitter Ads account** at [ads.twitter.com](https://ads.twitter.com)
2. **Add payment method** — credit card or IO
3. **Install Twitter pixel** on the landing page (or configure Conversions API)
4. **Create conversion event** — Events Manager → New Event → Website visits / Custom event
5. **Map events** — `signup_complete` event → Twitter conversion event
6. **Verify** — use Twitter's Event Manager to confirm pixel is firing

### Dashboard Filter

Filter analytics dashboard by `utm_source = "twitter"` to see paid traffic performance.

## API Campaign Creation

Automated campaign creation via the X (Twitter) Ads API. Used by `/distribute` Step 9 when credentials are available.

### Credential Files

| File | Contents |
|------|----------|
| `~/.x-ads/api-key` | API Key (Consumer Key) |
| `~/.x-ads/api-secret` | API Secret (Consumer Secret) |
| `~/.x-ads/access-token` | Access Token |
| `~/.x-ads/access-token-secret` | Access Token Secret |

### Credential Check

Check all 4 files exist with `test -f`. If any are missing, show which are missing and guide the user through the Setup steps below. Do not fall back to manual — credentials are required.

### Setup

1. **Create an X Developer Account** at [developer.x.com](https://developer.x.com) if you don't have one.
2. **Create an App** — go to the Developer Portal → Projects & Apps → Create App. Save the API Key to `~/.x-ads/api-key` and API Secret to `~/.x-ads/api-secret`.
3. **Request Ads API access** — apply for Ads API access at [developer.x.com/en/docs/twitter-ads-api](https://developer.x.com/en/docs/twitter-ads-api). This requires an approved developer account and an active X Ads account with a funding instrument (payment method).
4. **Generate access tokens** — in the Developer Portal, go to your App → Keys and Tokens → Generate Access Token and Secret (with read/write permissions). Save the Access Token to `~/.x-ads/access-token` and Access Token Secret to `~/.x-ads/access-token-secret`.
5. **Verify** — all 4 files should exist under `~/.x-ads/`.

### API Procedure

All API calls use the X Ads API (`https://ads-api.x.com/12/`) with **OAuth 1.0a** request signing using all 4 credentials (consumer key, consumer secret, access token, access token secret).

**Step 1: Get ads account ID**

```bash
twurl -H ads-api.x.com "/12/accounts" | jq '.data[0].id'
```

Or via curl with OAuth 1.0a signature:

```bash
curl -s "https://ads-api.x.com/12/accounts" \
  --oauth1 "$(cat ~/.x-ads/api-key):$(cat ~/.x-ads/api-secret):$(cat ~/.x-ads/access-token):$(cat ~/.x-ads/access-token-secret)"
```

Extract the `id` from `data[0]` — this is the ads account ID used in all subsequent calls.

**Step 2: Check funding instrument**

```bash
curl -s "https://ads-api.x.com/12/accounts/<account_id>/funding_instruments" \
  --oauth1 ...
```

Verify at least one active funding instrument exists. If none, stop and tell the user to add a payment method at [ads.x.com](https://ads.x.com).

**Step 3: Create campaign (PAUSED)**

```bash
curl -s -X POST "https://ads-api.x.com/12/accounts/<account_id>/campaigns" \
  --oauth1 ... \
  -H "Content-Type: application/json" \
  -d '{
    "name": "<campaign_name>",
    "funding_instrument_id": "<funding_instrument_id>",
    "daily_budget_amount_local_micro": <daily_budget_cents * 10000>,
    "total_budget_amount_local_micro": <total_budget_cents * 10000>,
    "start_time": "<ISO8601>",
    "end_time": "<ISO8601 + duration_days>",
    "entity_status": "PAUSED"
  }'
```

Extract `data.id` as the campaign ID.

**Step 4: Create line item(s)**

One line item per variant (if variants exist), otherwise a single line item:

```bash
curl -s -X POST "https://ads-api.x.com/12/accounts/<account_id>/line_items" \
  --oauth1 ... \
  -H "Content-Type: application/json" \
  -d '{
    "campaign_id": "<campaign_id>",
    "name": "<line_item_name>",
    "product_type": "PROMOTED_TWEETS",
    "placements": ["ALL_ON_TWITTER"],
    "objective": "WEBSITE_CLICKS",
    "bid_amount_local_micro": <max_cpe_cents * 10000>,
    "entity_status": "ACTIVE"
  }'
```

Extract `data.id` as the line item ID.

**Step 5: Set targeting**

For each targeting criterion from ads.yaml `targeting`:

**Interests:**
```bash
curl -s -X POST "https://ads-api.x.com/12/accounts/<account_id>/targeting_criteria" \
  --oauth1 ... \
  -H "Content-Type: application/json" \
  -d '{"line_item_id": "<line_item_id>", "targeting_type": "INTEREST", "targeting_value": "<interest_id>"}'
```

Look up interest IDs via `GET /12/targeting_criteria/interests`.

**Follower lookalikes:**
```bash
curl -s -X POST "https://ads-api.x.com/12/accounts/<account_id>/targeting_criteria" \
  --oauth1 ... \
  -H "Content-Type: application/json" \
  -d '{"line_item_id": "<line_item_id>", "targeting_type": "FOLLOWER_LOOKALIKES", "targeting_value": "<user_id>"}'
```

Look up user IDs for handles via `GET /2/users/by/username/<handle>`.

**Timeline keywords:**
```bash
curl -s -X POST "https://ads-api.x.com/12/accounts/<account_id>/targeting_criteria" \
  --oauth1 ... \
  -H "Content-Type: application/json" \
  -d '{"line_item_id": "<line_item_id>", "targeting_type": "BROAD_KEYWORD", "targeting_value": "<keyword>"}'
```

**Locations:**
```bash
curl -s -X POST "https://ads-api.x.com/12/accounts/<account_id>/targeting_criteria" \
  --oauth1 ... \
  -H "Content-Type: application/json" \
  -d '{"line_item_id": "<line_item_id>", "targeting_type": "LOCATION", "targeting_value": "<location_key>"}'
```

Look up location keys via `GET /12/targeting_criteria/locations?location_type=COUNTRY&q=United States`.

**Step 6: Create promoted tweets**

For each tweet in ads.yaml `tweets`, first create a nullcast (promoted-only) tweet:

```bash
curl -s -X POST "https://ads-api.x.com/12/accounts/<account_id>/tweet" \
  --oauth1 ... \
  -H "Content-Type: application/json" \
  -d '{"text": "<tweet_text>", "nullcast": true}'
```

Extract the `tweet_id`, then associate it with the line item:

```bash
curl -s -X POST "https://ads-api.x.com/12/accounts/<account_id>/promoted_tweets" \
  --oauth1 ... \
  -H "Content-Type: application/json" \
  -d '{"line_item_id": "<line_item_id>", "tweet_ids": ["<tweet_id>"]}'
```

### Response Handling

- **Campaign ID**: extract from the campaign creation response `data.id`.
- **Dashboard URL**: `https://ads.x.com/campaign/<account_id>/campaigns/<campaign_id>`
- **Status**: campaign is created in `PAUSED` status — the user enables it after verifying conversion tracking.

### Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| `UNAUTHORIZED` (401) | Invalid or expired OAuth credentials | Verify all 4 credential files are correct; regenerate tokens if needed |
| `FORBIDDEN` (403) on ads endpoints | Ads API access not approved | Apply for Ads API access (Setup step 3) and wait for approval |
| `NO_FUNDING_INSTRUMENT` | No payment method on the ads account | Add a payment method at [ads.x.com](https://ads.x.com) |
| `BUDGET_TOO_LOW` | Budget below platform minimum | Increase `daily_budget_cents` or `total_budget_cents` in ads.yaml |
| `RATE_LIMIT` (429) | Too many API requests | Wait for the rate limit window to reset (indicated in response headers) |
| Any other API error | Various | Report the full error message to the user and fall back to manual campaign creation (Step 9f) |
