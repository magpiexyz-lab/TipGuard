---
name: Crucible Design System
description: Assayer uses a "Crucible" design system -- warm obsidian dark-first palette with molten gold accents, Instrument Serif + DM Sans typography, noise/gradient/glass depth techniques
type: project
---

Assayer's visual identity is the "Crucible" design system, derived from the metallurgical assaying metaphor (testing ore for gold).

**Why:** The product delivers high-stakes SCALE/REFINE/PIVOT/KILL verdicts for startup ideas. The visual language must carry that gravity -- warm, rich, precise, not clinical or playful.

**How to apply:**
- Dark-first with warm hue angle (~55-80 oklch) running through all surfaces
- Molten gold (`oklch(0.78 0.155 75)`) is the signature accent color
- Display font: Instrument Serif (editorial authority), Body: DM Sans (geometric clarity)
- Depth via noise overlay + radial gradient mesh + glassmorphism
- Verdict colors are semantic: viridian (SCALE), amber (REFINE), copper (PIVOT), cinnabar (KILL)
- Custom Tailwind tokens: gold, ember, copper, mineral, obsidian, charcoal, ash, parchment, verdict-*
- All design tokens live in `src/app/globals.css`, visual brief at `.runs/current-visual-brief.md`
