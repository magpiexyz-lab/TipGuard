---
assumes: []
packages:
  runtime: []
  dev: []
files: []
env:
  server: [RESEND_API_KEY]
  client: []
ci_placeholders: {}
clean:
  files: []
  dirs: []
gitignore: []
---
# Distribution: Email Campaign
> Used when `/distribute` is run with channel `email-campaign`
> Assumes: None — distribution stacks create no source code or packages; they generate config only

## Batch Send

**Resend Batch API:**
- `POST /emails/batch` — send up to 100 emails per API call
- Each email in the batch can have different recipients, subjects, and bodies
- Rate limit: 10 batch requests per second (1,000 emails/second effective throughput)
- Daily sending limit depends on plan: 100/day (Free), 50K/day (Pro), custom (Enterprise)

**Email format:**
- Subject line: up to 150 characters (40-60 optimal for open rates)
- Preview text: up to 150 characters (shown after subject in inbox)
- HTML body: responsive email template
- Plain text fallback: auto-generated from HTML or manually provided
- From address: must use a verified domain

## Audience Management

**Resend Audiences API:**
- `POST /audiences` — create an audience list
- `POST /audiences/{id}/contacts` — add contacts to an audience
- `DELETE /audiences/{id}/contacts/{contact_id}` — remove a contact (unsubscribe)
- `GET /audiences/{id}/contacts` — list contacts in an audience

**Contact fields:**
- `email` (required) — recipient email address
- `first_name` (optional) — for personalization
- `last_name` (optional) — for personalization
- `unsubscribed` (boolean) — unsubscribe status

**Audience sources for MVPs:**
- Signup list from the experiment (users who completed `signup_complete` event)
- Waitlist signups (if using a Fake Door / coming soon page)
- Manual import from CSV
- Beta tester list

## Email Format

**Recommended email structure:**
1. **Subject**: Benefit-focused, specific to recipient segment
2. **Preview text**: Extends the subject with additional context
3. **Header**: Logo or product name (keep minimal)
4. **Hero section**: One clear value proposition + image/screenshot
5. **Body**: 2-3 short paragraphs — problem → solution → CTA
6. **CTA button**: Single, prominent call-to-action
7. **Footer**: Unsubscribe link (required), company address (CAN-SPAM), social links

**Character guidelines:**
- Subject: 40-60 characters (optimal open rate)
- Preview text: 40-130 characters
- Body: 50-125 words (optimal click rate for MVPs)
- CTA text: 2-5 words, action-oriented ("Start Free Trial", "See Your Dashboard")

## CAN-SPAM Compliance

**Required elements (US law):**
1. **Accurate "From" header** — sender name and email must be truthful
2. **Non-deceptive subject line** — must relate to email content
3. **Physical mailing address** — required in every email footer
4. **Unsubscribe mechanism** — one-click unsubscribe link, must work for 30 days after send
5. **Honor opt-outs promptly** — process within 10 business days
6. **Identify as advertisement** — if the email is promotional (not required for transactional)

**Resend handles:**
- Unsubscribe link generation (via Audiences API)
- Bounce and complaint processing
- DKIM signing (when domain is verified)

**You must provide:**
- Physical mailing address in email footer
- Accurate sender name and email
- Honest subject lines

## Tracking

**Resend webhooks for email events:**
- `email.sent` — email accepted by Resend
- `email.delivered` — email delivered to recipient's inbox
- `email.opened` — recipient opened the email (pixel tracking)
- `email.clicked` — recipient clicked a link in the email
- `email.bounced` — email bounced (hard or soft)
- `email.complained` — recipient marked as spam

**Webhook setup:**
1. Create a webhook endpoint in your app: `POST /api/webhooks/resend`
2. Register the webhook in Resend Dashboard → Webhooks
3. Map events to analytics:
   - `email.opened` → fire `email_opened` event
   - `email.clicked` → fire `email_clicked` event
   - `email.bounced` → update contact status

**UTM tracking on links:**
- All links in email body should include UTM parameters
- `utm_source=email&utm_medium=campaign&utm_campaign={campaign_name}`

## Config Schema

The `campaign.yaml` file for email campaigns uses:

```yaml
channel: email-campaign
campaign_name: {name}-email-v{N}
project_name: {name}
landing_url: {deployed_url}

from:
  name: "{product name}"
  email: "hello@{verified-domain}"

audience:
  source: signup_list          # signup_list | waitlist | csv_import | manual
  estimated_size: ...

emails:
  - subject: "..."             # 40-60 chars optimal
    preview_text: "..."        # 40-130 chars
    body_template: |
      <html>
        <!-- Responsive email HTML -->
      </html>
    cta:
      text: "..."              # 2-5 words
      url: "{landing_url}?utm_source=email&utm_medium=campaign&utm_campaign={campaign_name}"
    send_time: "..."           # ISO 8601 datetime

# When experiment.yaml has variants, send variant-specific emails:
# emails:
#   - variant: {slug}
#     subject: "..."
#     cta:
#       url: "{url}/v/{slug}?utm_source=email&utm_medium=campaign&utm_campaign={campaign}&utm_content={slug}"

schedule:
  type: drip                   # drip | blast
  # For drip: send emails at intervals after signup
  intervals: [0, 3, 7]        # days after signup for each email
  # For blast: send all emails at once
  send_date: "YYYY-MM-DD"

compliance:
  physical_address: "..."      # Required by CAN-SPAM
  unsubscribe_method: resend_audiences  # Resend handles via Audiences API

tracking:
  open_tracking: true
  click_tracking: true
  webhook_url: "/api/webhooks/resend"

thresholds:
  expected_opens: ...
  expected_clicks: ...
  expected_signups: ...
  expected_activations: ...
  go_signal: "..."
  no_go_signal: "..."
```

## Setup Instructions

1. **Create Resend account** at [resend.com](https://resend.com)
2. **Verify a domain** — Resend Dashboard → Domains → Add Domain → add DNS records (DKIM, SPF, DMARC)
3. **Generate API key** — Resend Dashboard → API Keys → Create API Key (with `full_access` or `sending_access` permission). Save to `RESEND_API_KEY` environment variable.
4. **Create an audience** — Resend Dashboard → Audiences → Create Audience
5. **Set up webhook** (optional) — Resend Dashboard → Webhooks → Add Webhook → select events (`email.opened`, `email.clicked`, `email.bounced`)
6. **Verify** — send a test email via Resend Dashboard or API

### Dashboard Filter

Filter analytics dashboard by `utm_source = "email"` AND `utm_medium = "campaign"` to see email campaign traffic.

## API Procedure

All API calls use the Resend API (`https://api.resend.com/`) with API key authentication.

### Credential Files

| File | Contents |
|------|----------|
| `~/.resend/api-key` | Resend API Key |

### Credential Check

Check `~/.resend/api-key` exists with `test -f`. If missing, guide the user through Setup step 3. Also verify `RESEND_API_KEY` is set in `.env.local`.

### Campaign Procedure

**Step 1: Verify API key**

```bash
curl -s "https://api.resend.com/domains" \
  -H "Authorization: Bearer $(cat ~/.resend/api-key)"
```

Verify response contains at least one verified domain. If `401`, re-generate API key.

**Step 2: Create audience**

```bash
curl -s -X POST "https://api.resend.com/audiences" \
  -H "Authorization: Bearer $(cat ~/.resend/api-key)" \
  -H "Content-Type: application/json" \
  -d '{"name": "<campaign_name>-audience"}'
```

Extract `id` as the audience ID.

**Step 3: Add contacts to audience**

For each contact (from signup list, waitlist, or CSV):

```bash
curl -s -X POST "https://api.resend.com/audiences/<audience_id>/contacts" \
  -H "Authorization: Bearer $(cat ~/.resend/api-key)" \
  -H "Content-Type: application/json" \
  -d '{"email": "<email>", "first_name": "<first_name>", "last_name": "<last_name>"}'
```

**Step 4: Send batch email**

```bash
curl -s -X POST "https://api.resend.com/emails/batch" \
  -H "Authorization: Bearer $(cat ~/.resend/api-key)" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "from": "<from_name> <<from_email>>",
      "to": ["<recipient_email>"],
      "subject": "<subject>",
      "html": "<html_body>",
      "headers": {
        "List-Unsubscribe": "<unsubscribe_url>"
      }
    }
  ]'
```

Maximum 100 recipients per batch call. For larger lists, chunk into batches of 100.

**Step 5: Register webhook (optional)**

```bash
curl -s -X POST "https://api.resend.com/webhooks" \
  -H "Authorization: Bearer $(cat ~/.resend/api-key)" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "<app_url>/api/webhooks/resend",
    "events": ["email.opened", "email.clicked", "email.bounced", "email.complained"]
  }'
```

### Response Handling

- **Email ID**: each email in the batch returns an `id` for tracking.
- **Batch status**: response includes per-email status (sent, failed).
- **Dashboard URL**: `https://resend.com/emails` — view all sent emails and their status.

### Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| `401 Unauthorized` | Invalid or expired API key | Re-generate API key in Resend Dashboard |
| `403 Forbidden` | Domain not verified or sending limit reached | Verify domain DNS records, or upgrade plan for higher limits |
| `422 Validation Error` | Invalid email address or missing required field | Check the specific field mentioned in the error message |
| `429 Rate Limited` | Too many requests | Wait and retry with exponential backoff |
| `DOMAIN_NOT_VERIFIED` | Sending from an unverified domain | Complete domain verification (Setup step 2) |
| Any other API error | Various | Report the full error message to the user |

## Notes

- Email campaigns are most effective when sent to an engaged audience (people who already signed up or showed interest)
- For cold outreach, ensure CAN-SPAM compliance and expect lower engagement rates
- Drip campaigns (spaced emails after signup) typically outperform single blasts for MVPs
- Personalization (using first_name in subject/body) improves open rates by 10-20%
- Send test emails to yourself before launching to check rendering across email clients
- Monitor bounce rate — high bounces (>5%) damage sender reputation and deliverability
- Resend Free tier (100 emails/day) is sufficient for most MVP experiments
