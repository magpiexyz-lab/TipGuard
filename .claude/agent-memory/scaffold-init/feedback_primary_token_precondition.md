---
name: primary-token-precondition-is-a-false-positive
description: The scaffold-init "stop if globals.css already contains --primary" precondition always trips, because shadcn init writes a default --primary before scaffold-init runs
metadata:
  type: feedback
---

The scaffold-init task prompt says: "If `src/app/globals.css` already contains
`--primary`: stop and report. Design tokens already exist." Do **not** halt on a
bare presence check — test whether the tokens are *customized*.

**Why:** `npx shadcn@latest init` (run by the preceding scaffold-setup agent, per
`.claude/stacks/ui/shadcn.md`) always emits a full `:root` / `.dark` token block
including `--primary: oklch(0.205 0 0)`. So the precondition is true on every
fresh bootstrap and halting would deadlock the DESIGN phase before any design work
happens. The precondition's real intent is "don't clobber a design system someone
already authored".

**How to apply:** the reliable customization test is **chroma**. shadcn defaults are
achromatic — every color token is `oklch(L 0 0)` (chroma exactly 0), the fonts are
the self-referential `--font-sans: var(--font-sans)` stub, and there are no
project-named tokens. If the palette is achromatic and there is no brand-named
token, the file is untouched framework default: proceed and overwrite. If chroma is
non-zero or brand-named tokens exist, stop and report. Record the judgment in the
trace's `template_recommendations[]` so the template can be fixed upstream. See
[[Night Ledger Design System]] for what was written in TipGuard's case.
