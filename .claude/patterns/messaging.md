# Conversion Messaging Framework

Shared copy and structure rules for landing pages (`/bootstrap`) and ad campaigns (`/distribute`).
Both skills derive conversion copy from `experiment.yaml` — this file ensures they say the same thing.

## Section A: Copy Derivation Rules

Derive all conversion copy from experiment.yaml fields. Never use raw field values as headlines.

### Headline

Formula: **"[Verb] [desired outcome] [qualifier]"** — derived from `description` (the solution aspect) + `target_user`, NOT from `name`.

- `name` is the product name/brand (e.g., "QuickBill — Fast Invoicing for Freelancers")
- The headline is the value proposition (e.g., "Invoice Clients in 60 Seconds")

Anti-pattern: using `name` as the headline. That's branding, not conversion.

### Subheadline

One sentence explaining HOW — derived from `description` (the solution aspect). Can use the first sentence more directly, but rewrite for clarity if needed.

### CTA

Formula: **"{action verb} + {outcome}"** — not generic labels like "Sign up" or "Get started".

Examples:
- "Send Your First Invoice"
- "Start Tracking Free"
- "Build Your First Page"

### Pain points

3 short statements derived from the problem described in `description`. Each addresses one aspect of the pain.

Format: icon/emoji + short statement (e.g., "Manual invoicing wastes hours every week").

## Section B: Landing Page Content Inventory

Content inventory for landing pages (raw material — page architecture is a
creative decision by `frontend-design`, not a fixed checklist):

- **Value proposition** — headline + subheadline (derived from Section A rules)
- **CTA** — the call-to-action (derived from Section A rules)
- **Pain points** — derived from the problem described in experiment.yaml `description` — aspects of the pain to activate
- **Features** — derived from experiment.yaml `behaviors` — capabilities to showcase
- **Social proof** — testimonials, logos, metrics (if available in experiment.yaml or inferable)

`frontend-design` decides which elements to include, how to arrange them, how
many times CTA appears, and what additional sections the page needs (comparison
tables, pricing, FAQ, demo, etc.). The content inventory is input, not structure.

When landing is the only page (features as sections), features become interactive
sections rather than descriptive cards.

> **Testing note**: CTA typically appears 2+ times on landing pages — test
> selectors targeting CTA buttons should use `.first()` to avoid ambiguous matches.

## Section C: Message Match Rules

Rules ensuring ad-to-landing consistency:

- Ad headlines MUST be derived from the same headline as the landing page (shortened to fit the channel's ad format constraints — see distribution stack file)
- Ad descriptions MUST match the landing page subheadline in meaning
- CTA language MUST be consistent across ads and landing page
- The landing page headline should be recognizable to someone who just clicked the ad

## Section D: Variant Messaging Rules

When experiment.yaml has a `variants` field, these rules extend Sections A–C:

### Variant Copy Source
- Each variant defines its own `headline`, `subheadline`, `cta`, and `pain_points`.
- These fields **replace** the copy that Section A would derive from `description` + `target_user`.
- The variant copy IS the messaging — do not re-derive from solution/target_user.

### Landing Page Structure
- Each variant uses the **same** page structure (chosen by AI at bootstrap). Variant fields slot into the shared layout.
- Variant fields slot into Hero and Pain Points. Features section is shared across all variants (from experiment.yaml `behaviors`).

### Default Variant
- The variant with `default: true` (or the first in the list) renders at root `/`.
- All variants also render at `/v/<slug>`.
- The default variant is accessible at both `/` and `/v/<default-slug>`.

### Message Match for Variants
- Section C rules apply **per variant**: each variant's ad group must match its landing page headline.
- Ad headlines for a variant are shortened from that variant's `headline` field, not from the shared `description`.

## Section E: SEO/AEO Metadata Derivation Rules

Derive SEO metadata from experiment.yaml fields. These rules feed `layout.tsx` metadata exports, `llms.txt`, and JSON-LD structured data.

### Display Name

Title-case the experiment.yaml `name` slug, replacing hyphens with spaces.

Example: `quick-bill` → `Quick Bill`, `page-forge` → `Page Forge`.

### Meta Title

Formula: **`{headline} | {display name}`** — must be 60 characters or fewer. If it exceeds 60 chars, shorten the headline portion (keep the display name intact).

### Meta Description

Benefit-focused rewrite of the subheadline (from Section A). Must be 160 characters or fewer. Focus on what the user gains, not how the product works.

### OG Title / OG Description

Same values as meta title and meta description respectively.

### llms.txt Content

Plain text file summarizing the product for AI search engines. Format:

```
# {display name}

> {meta description}

## Features

- {behavior 1 `then` field}
- {behavior 2 `then` field}
- ...
```

Derive all content from experiment.yaml fields (`name`, `description`, `behaviors`).

### Variant Override

When experiment.yaml has `variants`, the root layout metadata uses the **default variant's** headline and subheadline (or Section A derivation if no variants). Each variant page exports `generateMetadata()` using that variant's `headline` and `subheadline` to override layout defaults.

## Section F: Sitelink Copy Rules

Rules for generating Google Ads sitelink extension copy from `golden_path` step descriptions and behavior `then` clauses. Used by `/distribute` state-4 Step 4b.5.

### Input Sources

- **Step description**: the `step` field from `golden_path` (e.g., "Click 'New Invoice' on dashboard")
- **Behavior then clause**: the `then` field from the behavior matching the step's `event` (e.g., "Invoice is created with line items and sent to client email")
- **Page context**: what the destination page does (from the `golden_path` `page` field and experiment.yaml `description`)

### Copy Formulas

**link_text** (max 25 characters):
- Formula: `[imperative verb] [noun]` — the action the user takes on the destination page
- Derive the verb from the step description, the noun from the page purpose
- Examples: "Create an Invoice" (18), "View Dashboard" (14), "Track Payments" (14), "Sign Up Free" (12)
- Avoid generic CTAs: "Learn More", "Click Here", "Visit Page"

**description_1** (max 35 characters):
- Formula: benefit statement — what the user gains on this page
- Derive from the behavior's `then` clause (the outcome)
- Examples: "Send invoices in under 60 seconds" (33), "See all clients at a glance" (26)

**description_2** (max 35 characters):
- Formula: qualifier or differentiator — how or why this is valuable
- Derive from experiment.yaml `description` or the behavior's `given` clause
- Examples: "No accounting degree needed" (26), "Free for up to 5 clients" (24)

### Tone

- Action-oriented and specific to the destination page
- No superlatives ("best", "amazing") unless substantiated
- Consistent with the ad RSA copy and landing page messaging (Section C applies)

### Message Match

- Sitelink link_text must be consistent with the destination page's headline (if page exists)
- A user clicking a sitelink should see content that directly relates to the link_text they clicked

### Anchor Sitelinks

For anchor sitelinks (destination = `?...#section_id`), derive copy from the section content on the landing page:
- link_text should name the section purpose: "See Our Features" (16), "View Pricing" (12), "Read the FAQ" (12)
- Descriptions should describe what the section contains
