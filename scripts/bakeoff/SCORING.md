# Scoring Rubric

Each candidate scored on **5 universal dimensions + 1-2 slot-specific dimensions**.

## Universal (1-10 each)

1. **Subject relevance** — Does the image clearly relate to "Inkwell, an AI email copilot" and the slot's purpose? Off-topic = 1, perfectly matched = 10.
2. **Style cohesion** — Does this image share a visual system with other generated images for Inkwell? Uses the brand palette (#2D4A7C navy / #E8A87C orange / #F5F0EB cream / #2D2D2D charcoal)? Wildly different = 1, fully aligned = 10.
3. **Color harmony** — Palette feels intentional and complementary, not clashing or muddy.
4. **Compositional quality** — Intentional negative space, clear focal point, no awkward cropping or cluttered regions.
5. **Production polish** — No AI artifacts (distorted text, extra fingers, floating objects, inconsistent lighting, blur). Would pass as professional work at a glance.

## Slot-specific (1-10)

| Slot | Extra dimension | What we're measuring |
|---|---|---|
| `hero` | **Overlay headroom** | Negative space available for headline + CTA overlay (top 1/3 or right 1/3) |
| `feature-*` | **Illustration vs photo balance** | Bold flat illustration = 10, photorealistic = 1 (we want illustration here) |
| `logo` | **Vector cleanliness + scalability** | Clean SVG paths, readable at 16px favicon, no raster fallback |
| `og` | **Text rendering accuracy** | Spelled correctly, kerning intact, no glyph artifacts (THE key metric here) |
| `mockup` | **Background isolation + product fidelity** | True transparent edges, sharp UI rendering, no fake-screenshot artifacts |
| `empty-state` | **Friendliness + encouragement** | Warm, inviting, not sterile; user wouldn't bounce on seeing this |

## Scoring procedure

For each image:
1. Open with Read tool (it renders the image visually)
2. Score each dimension 1-10
3. Note 1-line "what works / what fails"
4. Watermark check (nano-banana-pro only): note if SynthID watermark is visible

## Aggregation

Per slot:
- **Per-dimension average** across 2 variants per model
- **Top model** per dimension
- **Overall winner** = highest sum across all dimensions
- **Recommended action**: Replace / Keep / A-B long-term / Not viable
