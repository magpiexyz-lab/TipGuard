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
# Distribution: Reddit Organic
> Used when `/distribute` is run with channel `reddit-organic`
> Assumes: None — distribution stacks create no source code or packages; they generate config only

## Post Format

**Link Post:**
- Title: up to 300 characters
- URL: the landing page link (Open Graph tags generate preview card)
- No body text — the link IS the content

**Text Post (self-post):**
- Title: up to 300 characters
- Body: up to 40,000 characters (Markdown supported)
- Can include links in body text
- Preferred for value-first content (tutorials, case studies, Show HN-style posts)

**Crosspost:**
- Share your post from one subreddit to another (if subreddit allows)
- Original post gets engagement from all crosspost locations

Minimum 3 post variations per campaign. Mix of link posts and text posts recommended.

## Subreddit Rules

**Before posting to any subreddit:**

1. Read the subreddit rules: `GET /r/{subreddit}/about/rules`
2. Check for self-promotion limits — most subreddits enforce the "10% rule" (no more than 10% of your posts should be self-promotion)
3. Check for flair requirements — some subreddits require specific post flair
4. Check for karma/age requirements — many subreddits require minimum account age (7-30 days) and/or minimum karma (10-100+)
5. Check for link post restrictions — some subreddits are text-only

**Common restrictions:**
- r/startups — no direct links to your product; text posts only with story/context
- r/SaaS — self-promotion allowed in designated threads only
- r/Entrepreneur — value-first posts only; no "check out my app" spam
- r/webdev — Show off Saturday/Sunday threads for project showcases

## Flair

Many subreddits require post flair. Common flair types:
- "Show /r/subreddit" — for showcasing your own project
- "Question" — for seeking feedback
- "Resource" — for sharing tools/tutorials
- "Discussion" — for open-ended topics

Read the subreddit's flair options via `GET /r/{subreddit}/api/link_flair_v2` and select the most appropriate one.

## Auth

**OAuth 2.0** — required for Reddit API.

Required scopes:
- `submit` — create posts
- `read` — read subreddit info and rules
- `flair` — set post flair
- `identity` — read authenticated user profile

Flow:
1. Create a "script" type app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)
2. Use client credentials (client ID + secret) for authentication
3. Obtain Bearer token via `POST https://www.reddit.com/api/v1/access_token`

## Rate Limits

**Reddit API rate limits:**
- **Global**: 10 requests per minute (100 requests per minute for OAuth apps)
- **Per-subreddit posting interval**: minimum 10 minutes between posts to the same subreddit
- **Account-level**: new accounts (<30 days) face stricter limits — 1 post per 10 minutes across all subreddits
- **Karma-based**: low-karma accounts (<10 combined karma) face additional restrictions

**Posting cadence recommendations:**
- 1 post per subreddit per day maximum
- Rotate across 3-5 subreddits
- Space posts at least 10 minutes apart
- Build karma with helpful comments before posting (organic credibility)

## Measurement

Organic Reddit posts have limited built-in analytics. Measure via:
1. **UTM parameters** on links — track `utm_source=reddit&utm_medium=organic` in analytics
2. **Reddit native metrics** — upvotes, comments, upvote ratio (visible on post)
3. **Click-through rate** — approximate via `visit_landing` events with `utm_source=reddit` vs. Reddit-reported views
4. **Conversion** — `visit_landing` events with `utm_source=reddit` in your analytics dashboard

No click ID equivalent for organic — attribution relies entirely on UTM parameters.

## Config Schema

The `organic.yaml` file for Reddit organic uses:

```yaml
channel: reddit-organic
campaign_name: {name}-reddit-organic-v{N}
project_name: {name}
landing_url: {deployed_url}

posts:
  - subreddit: "..."           # Target subreddit (without r/ prefix)
    title: "..."               # up to 300 chars
    type: link                 # link | text
    url: "..."                 # for link posts: landing URL with UTM
    body: "..."                # for text posts: Markdown body
    flair: "..."               # post flair (check subreddit requirements)
    schedule: "..."            # ISO 8601 datetime or relative

  - subreddit: "..."
    title: "..."
    type: text
    body: |
      Value-first content here...

      [Try it out]({landing_url}?utm_source=reddit&utm_medium=organic&utm_campaign={campaign}&utm_content={subreddit})
    flair: "Show r/..."

# When experiment.yaml has variants, include utm_content in landing URLs:
# posts:
#   - subreddit: "..."
#     variant: {slug}
#     url: "{url}/v/{slug}?utm_source=reddit&utm_medium=organic&utm_campaign={campaign}&utm_content={slug}"

schedule:
  start_date: "YYYY-MM-DD"
  duration_days: ...
  posts_per_day: 1-2
  best_times: ["8:00 AM EST", "6:00 PM EST"]

targeting:
  subreddits: [...]            # 3-5 target subreddits
  post_types: [link, text]     # Mix of post types
  engagement_strategy: "..."   # How to participate in comments

thresholds:
  expected_upvotes: ...
  expected_comments: ...
  expected_link_clicks: ...
  expected_signups: ...
  go_signal: "..."
  no_go_signal: "..."
```

## Setup Instructions

1. **Reddit account** — use an existing account with some karma, or build karma on a new account (7+ days, 10+ karma recommended)
2. **Create a Reddit app** — go to [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → Create App → "script" type
3. **Save credentials** — note the client ID (under app name) and client secret
4. **Review target subreddits** — read rules, check flair requirements, note posting restrictions
5. **Build credibility** — post helpful comments in target subreddits before self-promoting (Reddit community strongly penalizes drive-by self-promotion)
6. **Verify** — make a test post to a low-traffic subreddit (e.g., r/test)

### Dashboard Filter

Filter analytics dashboard by `utm_source = "reddit"` AND `utm_medium = "organic"` to see organic Reddit traffic.

## API Procedure

All API calls use the Reddit API (`https://oauth.reddit.com/`) with OAuth 2.0 Bearer token.

### Credential Files

| File | Contents |
|------|----------|
| `~/.reddit-organic/client-id` | Reddit App Client ID |
| `~/.reddit-organic/client-secret` | Reddit App Client Secret |
| `~/.reddit-organic/username` | Reddit username |
| `~/.reddit-organic/password` | Reddit password |

### Credential Check

Check all 4 files exist with `test -f`. If missing, guide the user through the Setup steps above.

### Posting Procedure

**Step 1: Obtain access token**

```bash
curl -s -X POST "https://www.reddit.com/api/v1/access_token" \
  -u "$(cat ~/.reddit-organic/client-id):$(cat ~/.reddit-organic/client-secret)" \
  -d "grant_type=password&username=$(cat ~/.reddit-organic/username)&password=$(cat ~/.reddit-organic/password)"
```

Extract `access_token` from the response. Token is valid for 1 hour.

**Step 2: Check subreddit rules**

```bash
curl -s "https://oauth.reddit.com/r/<subreddit>/about/rules" \
  -H "Authorization: Bearer <access_token>" \
  -H "User-Agent: <app_name>/1.0"
```

Review rules before posting. Abort if the post would violate subreddit rules.

**Step 3: Get available flair**

```bash
curl -s "https://oauth.reddit.com/r/<subreddit>/api/link_flair_v2" \
  -H "Authorization: Bearer <access_token>" \
  -H "User-Agent: <app_name>/1.0"
```

Select the most appropriate flair ID for the post.

**Step 4: Submit a link post**

```bash
curl -s -X POST "https://oauth.reddit.com/api/submit" \
  -H "Authorization: Bearer <access_token>" \
  -H "User-Agent: <app_name>/1.0" \
  -d "sr=<subreddit>&kind=link&title=<title>&url=<url_with_utm>&flair_id=<flair_id>&api_type=json"
```

**Step 5: Submit a text post**

```bash
curl -s -X POST "https://oauth.reddit.com/api/submit" \
  -H "Authorization: Bearer <access_token>" \
  -H "User-Agent: <app_name>/1.0" \
  -d "sr=<subreddit>&kind=self&title=<title>&text=<body_markdown>&flair_id=<flair_id>&api_type=json"
```

Extract `data.url` as the post URL.

### Response Handling

- **Post ID**: extract from `data.name` (format: `t3_XXXXXX`).
- **Post URL**: extract from `data.url` or construct: `https://www.reddit.com/r/<subreddit>/comments/<id>/`
- **Check post status**: if `data.drafts_count` is returned, the post may be held for moderator review.

### Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| `403 Forbidden` | Account lacks karma/age for this subreddit | Build karma with comments first, or try a less restrictive subreddit |
| `SUBREDDIT_NOEXIST` | Subreddit name is wrong | Verify subreddit exists and is not private |
| `RATELIMIT` | Too many posts too quickly | Wait the specified time (error message includes wait duration) |
| `NO_SELFS` | Subreddit doesn't allow text posts | Use a link post instead |
| `NO_LINKS` | Subreddit doesn't allow link posts | Use a text post with link in body |
| Any other API error | Various | Report the full error message to the user |

## Notes

- Reddit is hostile to overt self-promotion — lead with value, not with your product
- The best-performing Reddit posts tell a story: "I built X because I had problem Y, here's what I learned"
- Engage genuinely in comments on your posts — Reddit users can detect inauthentic engagement
- Consider posting in weekly self-promotion threads (many subreddits have dedicated threads)
- Timing matters: weekday mornings (US Eastern) tend to get the most visibility
- Cross-posting from a smaller subreddit to a larger one can amplify reach
- Account reputation is cumulative — consistent helpful participation builds credibility over time
