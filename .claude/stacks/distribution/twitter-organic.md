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
# Distribution: Twitter/X Organic
> Used when `/distribute` is run with channel `twitter-organic`
> Assumes: None — distribution stacks create no source code or packages; they generate config only

## Post Format

**Single Tweet:**
- Text: up to 280 characters
- Optional media: up to 4 images (1200×675px recommended) or 1 video (up to 2:20)
- Optional link: auto-generates a preview card from the URL's Open Graph tags
- Minimum 3 post variations per campaign

**Thread (multi-tweet):**
- Up to 25 tweets per thread
- First tweet is the hook — must stand alone as compelling content
- Last tweet contains the CTA + link
- Middle tweets provide value (tips, data, story beats)
- Thread unroll services (Typefully, Thread Reader) can boost reach

## Auth

**OAuth 2.0 with PKCE** — required for X API v2 posting.

Required scopes:
- `tweet.write` — create tweets and threads
- `tweet.read` — read tweets (for thread context)
- `users.read` — read authenticated user profile

OAuth 2.0 PKCE flow (no client secret needed for public clients):
1. Generate code verifier and challenge
2. Redirect to `https://twitter.com/i/oauth2/authorize` with `code_challenge` and scopes
3. Exchange authorization code for access token at `https://api.twitter.com/2/oauth2/token`
4. Use Bearer token for all subsequent API calls

## Rate Limits

**X API v2 rate limits (Free tier):**
- `POST /2/tweets`: 17 requests per 24 hours per user (Free), 100/day (Basic), 10K/month (Pro)
- `GET /2/tweets`: 100 requests per 15 minutes per user
- `GET /2/users/me`: 25 requests per 15 minutes per user

**Posting cadence recommendations:**
- 1-3 tweets per day maximum for organic reach
- Space posts 2-4 hours apart for optimal visibility
- Threads count as 1 rate-limit request per tweet in the thread

## Measurement

Organic posts have no built-in conversion tracking. Measure via:
1. **UTM parameters** on links — track `utm_source=twitter&utm_medium=organic` in analytics
2. **X Analytics** (native) — impressions, engagements, link clicks, profile visits
3. **Click-through rate** — link clicks / impressions from X Analytics
4. **Conversion** — `visit_landing` events with `utm_source=twitter` in your analytics dashboard

No click ID equivalent for organic — attribution relies entirely on UTM parameters.

## Config Schema

The `organic.yaml` file for Twitter organic uses:

```yaml
channel: twitter-organic
campaign_name: {name}-twitter-organic-v{N}
project_name: {name}
landing_url: {deployed_url}

posts:
  - text: "..."               # up to 280 chars, hook + value + CTA
    media: []                  # optional: image URLs or paths
    schedule: "..."            # ISO 8601 datetime or relative ("day 1 9:00 AM EST")

  # Thread format:
  - thread:
      - text: "..."            # Hook tweet (1/N)
      - text: "..."            # Value tweets (2-24/N)
      - text: "..."            # CTA tweet (N/N) — includes landing_url with UTM

# When experiment.yaml has variants, include utm_content in landing URLs:
# posts:
#   - text: "..."
#     variant: {slug}
#     landing_url: "{url}/v/{slug}?utm_source=twitter&utm_medium=organic&utm_campaign={campaign}&utm_content={slug}"

schedule:
  start_date: "YYYY-MM-DD"
  duration_days: ...
  posts_per_day: 1-3
  best_times: ["9:00 AM EST", "12:00 PM EST", "5:00 PM EST"]

targeting:
  hashtags: [...]              # 2-3 relevant hashtags per post
  mentions: [...]              # @handles to engage with (influencers, communities)
  topics: [...]                # Content themes to rotate

thresholds:
  expected_impressions: ...
  expected_link_clicks: ...
  expected_signups: ...
  go_signal: "..."
  no_go_signal: "..."
```

## Setup Instructions

1. **X Developer Account** — create at [developer.x.com](https://developer.x.com) (Free tier is sufficient for organic posting)
2. **Create an App** — Developer Portal → Projects & Apps → Create App
3. **Configure OAuth 2.0** — enable OAuth 2.0 with PKCE, set callback URL to `http://localhost:3000/callback`
4. **Generate credentials** — save Client ID for OAuth 2.0 PKCE flow
5. **Verify** — test a tweet via API: `POST /2/tweets` with `{"text": "Test post"}`

### Dashboard Filter

Filter analytics dashboard by `utm_source = "twitter"` AND `utm_medium = "organic"` to see organic Twitter traffic.

## API Procedure

All API calls use the X API v2 (`https://api.twitter.com/2/`) with OAuth 2.0 Bearer token.

### Credential Files

| File | Contents |
|------|----------|
| `~/.x-organic/client-id` | OAuth 2.0 Client ID |
| `~/.x-organic/access-token` | OAuth 2.0 Access Token (from PKCE flow) |

### Credential Check

Check both files exist with `test -f`. If missing, guide the user through the Setup steps above and the OAuth 2.0 PKCE flow.

### Posting Procedure

**Step 1: Verify authentication**

```bash
curl -s "https://api.twitter.com/2/users/me" \
  -H "Authorization: Bearer $(cat ~/.x-organic/access-token)"
```

Verify response contains user data. If `401`, re-run OAuth 2.0 PKCE flow.

**Step 2: Post a single tweet**

```bash
curl -s -X POST "https://api.twitter.com/2/tweets" \
  -H "Authorization: Bearer $(cat ~/.x-organic/access-token)" \
  -H "Content-Type: application/json" \
  -d '{"text": "<tweet_text>"}'
```

Extract `data.id` as the tweet ID.

**Step 3: Post a thread**

Post the first tweet (Step 2), then reply to it in sequence:

```bash
curl -s -X POST "https://api.twitter.com/2/tweets" \
  -H "Authorization: Bearer $(cat ~/.x-organic/access-token)" \
  -H "Content-Type: application/json" \
  -d '{"text": "<reply_text>", "reply": {"in_reply_to_tweet_id": "<previous_tweet_id>"}}'
```

Repeat for each tweet in the thread, using the previous tweet's ID as `in_reply_to_tweet_id`.

**Step 4: Upload media (optional)**

Media upload uses X API v1.1 (not v2):

```bash
curl -s -X POST "https://upload.twitter.com/1.1/media/upload.json" \
  -H "Authorization: Bearer $(cat ~/.x-organic/access-token)" \
  -F "media=@<image_path>"
```

Extract `media_id_string`, then include in the tweet:

```bash
curl -s -X POST "https://api.twitter.com/2/tweets" \
  -H "Authorization: Bearer $(cat ~/.x-organic/access-token)" \
  -H "Content-Type: application/json" \
  -d '{"text": "<tweet_text>", "media": {"media_ids": ["<media_id>"]}}'
```

### Response Handling

- **Tweet ID**: extract from `data.id` in the creation response.
- **Tweet URL**: `https://x.com/<username>/status/<tweet_id>`
- **Thread URL**: URL of the first tweet in the thread.

### Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| `401 Unauthorized` | Expired or invalid access token | Re-run OAuth 2.0 PKCE flow to get a new token |
| `403 Forbidden` | Missing required scope or app not approved | Verify app has `tweet.write` scope enabled |
| `429 Too Many Requests` | Rate limit exceeded (17/day on Free tier) | Wait until the rate limit window resets (check `x-rate-limit-reset` header) |
| `400 Duplicate Content` | Same tweet text posted recently | Modify the tweet text slightly and retry |
| Any other API error | Various | Report the full error message to the user |

## Notes

- Organic reach on X is highly variable — engagement (replies, retweets) significantly amplifies reach
- Posting during peak hours (9 AM, 12 PM, 5 PM in target timezone) improves visibility
- Threads generally outperform single tweets for informational content
- Hashtags: use 1-3 per tweet maximum — over-hashtagging reduces perceived quality
- Engage with replies to your posts — the algorithm favors active conversations
- Consider Quote Tweeting relevant industry posts with your take + landing URL
