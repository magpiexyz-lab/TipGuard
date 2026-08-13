---
name: elev-utilities-kill-tailwind-ring
description: In this repo, any element with both `elev-*` and `ring-*` renders NO ring — verify emphasis borders with computed styles, never by eye.
metadata:
  type: project
---

`src/app/globals.css` defines `.elev-1` / `.elev-2` / `.elev-3` with a bare
`box-shadow:` declaration inside `@layer utilities`. Because that block is
authored after `@import "tailwindcss"`, it is emitted *after* Tailwind's ring
utilities and overwrites `--tw-ring-shadow`. Result: on any element carrying
both an `elev-*` class and a `ring-*` class, the ring renders nothing —
computed `outline` is `none` and `box-shadow` contains only the elevation.

This silently kills shadcn `Card`'s own base `ring-1 ring-foreground/10` too,
since the project layers `elev-*` onto Cards throughout.

**Why:** found on `/pricing` (2026-08-11), where the Shield plan card's
`ring-2 ring-brass` "recommended plan" emphasis — the single strongest visual
signal on the paid-conversion page — had never rendered. It was invisible in
review screenshots precisely because a missing 2px edge looks like a design
choice, not a bug.

**How to apply:**
- Treat `ring-*` as unusable anywhere `elev-*` is present. Use `outline-2
  outline-<color>` instead — `outline` is a separate property, survives the
  override, and follows `rounded-*` radii.
- When reviewing any card/panel that claims an emphasis border, confirm it with
  `getComputedStyle(el).outlineStyle` + `.boxShadow` rather than by eye. The
  fast isolation check: compile `npx @tailwindcss/cli -i src/app/globals.css`
  and render the exact class string in a `file://` page.
- Root cause lives in `globals.css`, which is outside per-page design-critic
  FILE_BOUNDARYs — record it under `shared_issues`, fix locally with `outline-*`.
- Related trap in the same file: base `h1..h4 { letter-spacing: -1.2px }` is an
  absolute value tuned for 44px+ display text, so any shadcn primitive that
  renders a heading tag at UI size (`AccordionTrigger` is an `h3`) comes out
  visibly jammed. See [[shared-globals-css-typography-trap]].
