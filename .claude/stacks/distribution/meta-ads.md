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
# Distribution: Meta Ads
> Used when `/distribute` is run with channel `meta-ads`
> Assumes: None — distribution stacks create no source code or packages; they generate config only

## Ad Format Constraints

**Single Image Ads (Feed):**
- Primary text: up to 125 characters (recommended), 2200 max
- Headline: up to 40 characters (recommended), 255 max
- Description: up to 30 characters (recommended)
- Image: 1080×1080px (1:1) or 1200×628px (1.91:1), max 30MB
- Minimum 2 ad variations per campaign

**Carousel Ads (optional):**
- 2-10 cards per ad
- Each card: headline (40 chars), description (20 chars), image (1080×1080px)

## Targeting Model

**Interest-based targeting** — ads appear in feeds of users matching your criteria.

Targeting options:
- **Interests** — select from Meta's interest taxonomy (e.g., "Entrepreneurship", "Freelancing", "Small business")
- **Behaviors** — target based on purchase behavior, device usage, travel patterns
- **Demographics** — age, gender, education, job title
- **Lookalike audiences** — target users similar to a seed audience (requires existing pixel data)
- **Custom audiences** — retargeting via Meta Pixel (requires pixel installation)

Minimum targeting:
- At least 3 interests OR 2 behaviors OR a lookalike audience
- Recommended audience size: 500K–5M for cold traffic

No overly narrow targeting initially — let Meta's algorithm optimize delivery.

## Click ID

**Parameter name:** `fbclid` (Facebook Click ID)

Meta auto-appends `fbclid` to the landing URL when a user clicks an ad. Capture it on the landing page and include it in analytics events for offline conversion matching.

## Conversion Tracking

1. Install the Meta Pixel on the landing page
2. Configure the Conversions API (CAPI) for server-side event deduplication
3. Map the `signup_complete` event → Meta standard event (`Lead` or custom conversion)
4. Verify with Meta Events Manager → Test Events tool

Import method: Meta Pixel (client-side) + Conversions API (server-side, recommended for reliability).

## Policy Restrictions

**Restricted industries:**
- **DeFi protocols, ICOs, token sales** — **RESTRICTED**. Requires prior written permission from Meta. Apply via the Meta cryptocurrency advertising eligibility form.
- **Crypto exchanges/wallets** — **RESTRICTED**. Requires regulatory licenses (FinCEN MSB, state licenses in US, or MiCA CASP in EU) AND Meta cryptocurrency advertising pre-approval.
- **Gambling, pharma, weapons** — various restrictions apply; check Meta Advertising Standards.

**Compliance notes:**
- Landing page must match ad content (no bait-and-switch)
- Ads cannot make misleading claims about results or guarantees
- Personal attributes policy: avoid implying knowledge of personal characteristics ("Are you struggling with...?" is rejected)
- Review [Meta Advertising Standards](https://www.facebook.com/policies/ads/) before launching

## Cost Model

**CPM (Cost Per Mille/1000 impressions)** — Meta primarily uses impression-based pricing.

- Bidding strategy (Phase 1): `lowest_cost` — Meta optimizes for maximum results within budget
- After sufficient conversion data (50+ per week): switch to `cost_cap` — Meta optimizes for your target CPA
- `guardrails.cost_cap_cents` sets a ceiling on cost per result

Budget structure:
- `daily_budget_cents`: daily spend cap
- `total_budget_cents`: total campaign cap (max 50000 / $500 without explicit override)
- `duration_days`: campaign length (set based on experiment duration)

## Config Schema

The `ads.yaml` file for Meta Ads uses:

```yaml
channel: meta-ads
campaign_name: {name}-meta-v{N}
project_name: {name}
landing_url: {deployed_url}

targeting:
  interests: [...]           # 3+ interest categories
  behaviors: [...]           # optional behavior targeting
  demographics:
    age_min: 18
    age_max: 65
  locations: [US]
  languages: [en]

ads:
  - primary_text: "..."      # up to 125 chars recommended
    headline: "..."           # up to 40 chars recommended
    description: "..."        # up to 30 chars
    image: "..."              # 1080x1080px or 1200x628px

# When experiment.yaml has variants, use ad_sets instead of ads:
# ad_sets:
#   - variant: {slug}
#     landing_url: "{url}/v/{slug}?utm_source=facebook&utm_medium=paid_social&utm_campaign={campaign}&utm_content={slug}"
#     ads:
#       - primary_text: "..."
#         headline: "..."
#         description: "..."
#         image: "..."

budget:
  daily_budget_cents: ...
  total_budget_cents: ...
  duration_days: ...
  bidding_strategy: lowest_cost

conversions:
  primary_action: signup_complete
  secondary_actions: [activate]
  import_method: meta_pixel_and_capi

guardrails:
  cost_cap_cents: ...        # max cost per result (when using cost_cap strategy)
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

- `utm_source=facebook`
- `utm_medium=paid_social`
- `utm_campaign={campaign_name}`
- `utm_content={variant_slug}` (when using variants)

## Setup Instructions

1. **Create Meta Business Manager** at [business.facebook.com](https://business.facebook.com)
2. **Create an Ad Account** under the Business Manager
3. **Add payment method** — credit card or PayPal
4. **Install Meta Pixel** on the landing page
5. **Configure Conversions API** — see analytics stack file for server-side integration
6. **Create custom conversion** — Events Manager → Custom Conversions → map `signup_complete` event
7. **Verify** — use Meta Events Manager → Test Events to confirm pixel fires

### Dashboard Filter

Filter analytics dashboard by `utm_source = "facebook"` to see paid traffic performance.

## API Campaign Creation

Automated campaign creation via the Meta Marketing API. Used by `/distribute` Step 9 when credentials are available.

### Credential Files

| File | Contents |
|------|----------|
| `~/.meta-ads/app-id` | Meta App ID |
| `~/.meta-ads/app-secret` | Meta App Secret |
| `~/.meta-ads/access-token` | Long-lived User Access Token |
| `~/.meta-ads/ad-account-id` | Ad Account ID (format: `act_XXXXXXXXX`) |

### Credential Check

Check all 4 files exist with `test -f`. If any are missing, show which are missing and guide the user through the Setup steps below. Do not fall back to manual — credentials are required.

### Setup

1. **Create a Meta App** at [developers.facebook.com](https://developers.facebook.com) → My Apps → Create App → Business type. Save the App ID to `~/.meta-ads/app-id` and App Secret to `~/.meta-ads/app-secret`.
2. **Add the Marketing API product** — in the App Dashboard, go to Add Products → Marketing API → Set Up.
3. **Generate a User Access Token** — go to the Marketing API → Tools → Access Token Tool. Select permissions: `ads_management`, `ads_read`, `business_management`. Generate the token. Save to `~/.meta-ads/access-token`.
4. **Exchange for a long-lived token** (recommended — short-lived tokens expire in 1 hour):
   ```bash
   curl -s "https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id=$(cat ~/.meta-ads/app-id)&client_secret=$(cat ~/.meta-ads/app-secret)&fb_exchange_token=$(cat ~/.meta-ads/access-token)"
   ```
   Save the new `access_token` from the response to `~/.meta-ads/access-token` (overwrites the short-lived one). Long-lived tokens last ~60 days.
5. **Get your Ad Account ID** — go to Business Manager → Business Settings → Ad Accounts. The ID format is `act_XXXXXXXXX`. Save to `~/.meta-ads/ad-account-id`.
6. **Verify** — all 4 files should exist under `~/.meta-ads/`.

### API Procedure

All API calls use the Meta Marketing API (`https://graph.facebook.com/v21.0/`) with the access token as a query parameter or header.

**Step 1: Verify access token**

```bash
curl -s "https://graph.facebook.com/v21.0/me?access_token=$(cat ~/.meta-ads/access-token)"
```

Verify the response contains a valid user ID. If the token is expired, re-run Setup step 3-4.

**Step 2: Verify ad account access**

```bash
curl -s "https://graph.facebook.com/v21.0/$(cat ~/.meta-ads/ad-account-id)?fields=name,account_status,currency&access_token=$(cat ~/.meta-ads/access-token)"
```

Verify `account_status` is `1` (ACTIVE). If not, check Business Manager settings.

**Step 3: Create campaign (PAUSED)**

```bash
curl -s -X POST "https://graph.facebook.com/v21.0/$(cat ~/.meta-ads/ad-account-id)/campaigns" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "<campaign_name>",
    "objective": "OUTCOME_TRAFFIC",
    "status": "PAUSED",
    "special_ad_categories": [],
    "access_token": "<access_token>"
  }'
```

Extract `id` as the campaign ID.

**Step 4: Create ad set(s)**

One ad set per variant (if variants exist), otherwise a single ad set:

```bash
curl -s -X POST "https://graph.facebook.com/v21.0/$(cat ~/.meta-ads/ad-account-id)/adsets" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "<ad_set_name>",
    "campaign_id": "<campaign_id>",
    "daily_budget": <daily_budget_cents>,
    "billing_event": "IMPRESSIONS",
    "optimization_goal": "LINK_CLICKS",
    "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
    "targeting": {
      "geo_locations": {"countries": ["US"]},
      "age_min": 18,
      "age_max": 65,
      "interests": [{"id": "<interest_id>", "name": "<interest_name>"}]
    },
    "start_time": "<ISO8601>",
    "end_time": "<ISO8601 + duration_days>",
    "status": "ACTIVE",
    "access_token": "<access_token>"
  }'
```

Look up interest IDs via `GET /v21.0/search?type=adinterest&q=<keyword>&access_token=<token>`.

**Step 5: Upload ad creative image**

```bash
curl -s -X POST "https://graph.facebook.com/v21.0/$(cat ~/.meta-ads/ad-account-id)/adimages" \
  -F "filename=@<image_path>" \
  -F "access_token=<access_token>"
```

Extract `images.<filename>.hash` from the response.

**Step 6: Create ad creative**

```bash
curl -s -X POST "https://graph.facebook.com/v21.0/$(cat ~/.meta-ads/ad-account-id)/adcreatives" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "<creative_name>",
    "object_story_spec": {
      "page_id": "<page_id>",
      "link_data": {
        "message": "<primary_text>",
        "link": "<landing_url_with_utm>",
        "name": "<headline>",
        "description": "<description>",
        "image_hash": "<image_hash>"
      }
    },
    "access_token": "<access_token>"
  }'
```

**Step 7: Create ad**

```bash
curl -s -X POST "https://graph.facebook.com/v21.0/$(cat ~/.meta-ads/ad-account-id)/ads" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "<ad_name>",
    "adset_id": "<ad_set_id>",
    "creative": {"creative_id": "<creative_id>"},
    "status": "ACTIVE",
    "access_token": "<access_token>"
  }'
```

**Step 8: Install Meta Pixel on landing page**

Add the Meta Pixel base code to the landing page `<head>`:

```html
<script>
!function(f,b,e,v,n,t,s)
{if(f.fbq)return;n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)};
if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];
s.parentNode.insertBefore(t,s)}(window, document,'script',
'https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '<PIXEL_ID>');
fbq('track', 'PageView');
</script>
```

### Response Handling

- **Campaign ID**: extract from the campaign creation response `id`.
- **Dashboard URL**: `https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=<ad_account_id>&campaign_ids=<campaign_id>`
- **Status**: campaign is created in `PAUSED` status — the user enables it after verifying conversion tracking.

### Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| `OAuthException` (code 190) | Expired or invalid access token | Re-run Setup steps 3-4 to generate a new long-lived token |
| Error code `#1` | Unknown error / API rate limit | Wait 5 minutes and retry; if persistent, check [Meta API Status](https://metastatus.com/) |
| Error code `#17` | API rate limit exceeded | Wait for the rate limit window to reset (check `x-business-use-case-usage` header) |
| Error code `#100` | Invalid parameter | Check the specific `error_subcode` and `message` for which parameter is wrong |
| `ACCOUNT_NOT_ACTIVE` | Ad account is disabled | Re-enable in Business Manager → Ad Accounts |
| Any other API error | Various | Report the full error message to the user and fall back to manual campaign creation (Step 9f) |
