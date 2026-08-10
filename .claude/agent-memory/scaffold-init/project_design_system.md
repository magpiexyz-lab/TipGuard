---
name: Night Ledger Design System
description: TipGuard uses the "Night Ledger" design system — warm oat-paper light-first palette, olive ledger ink, brass seal accent, Fraunces + IBM Plex Sans/Mono typography, paper-grain and ruled-hairline depth
metadata:
  type: project
---

TipGuard's visual identity is the "Night Ledger" design system, derived from the
physical artifact the product replaces: the signed tip-credit notice and the dated
audit file.

**Why:** the register is fear-led B2B compliance sold to a restaurant operator, not
an enterprise legal buyer. It must read evidence-grade (this is what you hand a DOL
investigator) while staying approachable to a non-lawyer running a bar. Cool-neutral
B2B blue-gray is exactly what every competitor (Gusto, ADP, TipHaus, Toast) ships and
what this buyer ignores; alarm-red-everywhere reads as a scam. Credible fear is quiet.

**How to apply:**
- **Light-first, warm.** Oat paper `#F3F0E6` background; full-bleed olive-ink
  `#171C13` bands are the structural counter-surface and the dark mode.
- **Exactly 3 brand colors:** `--ink #171C13` (typography/authority),
  `--brass #C89230` (CTA + accent + at-risk flag), `--seal #2F6B4E` (signed /
  compliant). `--ember #A93B24` is `--destructive` only, capped at badges.
- **Brass is never text on a light surface** (2.42:1) — use `--brass-deep #8A5F14`.
- **Fonts:** Fraunces (display, variable opsz/SOFT/WONK) + IBM Plex Sans (body) +
  IBM Plex Mono (all legal/financial figures, dates, §citations, rule versions).
  The mono-for-evidence rule is the signature texture and is non-negotiable.
- **Depth:** SVG paper grain, 32px ruled ledger hairlines, brass radial bloom,
  brass-tinted multi-layer shadows. No gradient meshes, no glassmorphism.
- **Signature animation:** "The Signature" — signature stroke draws, brass seal
  stamps, status chip flips DRAFT → SIGNED with a UTC timestamp.
- **Proof is cited statute, never testimonials or logo walls** — fabricated social
  proof is disqualifying for a compliance product.
- Tokens live in `src/app/globals.css`; full brief at `.runs/current-visual-brief.md`
  (ephemeral — deleted after the bootstrap PR); per-slot image intent at
  `.runs/slot-intent.json`.
