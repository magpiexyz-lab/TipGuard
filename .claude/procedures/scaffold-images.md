# Scaffold: AI Image Generation (Multi-Model)

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table.
> web-app: full image generation | service/cli: skip (production_method='none' for non-web-app slots)

## Prerequisites
- Branch already created (by bootstrap Step 0)
- Plan approved and saved to `.runs/current-plan.md`
- Packages installed (by scaffold-setup agent)
- Visual brief written at `.runs/current-visual-brief.md` (by scaffold-init agent)
- `image_gen_status: "available"` in `.runs/bootstrap-context.json`
- Read all context files listed in your task assignment before starting

## Steps

### Step 1: Read context and derive visual system prefix
1. Read `.runs/current-visual-brief.md` — focus on **Image Direction** (all 7 sub-sections), **Color Palette**, and **Design Constraints**
2. Read `experiment/experiment.yaml` — extract `name`, `description`, `target_user`, and product domain
3. Read `.claude/stacks/images/fal.md` — study the model selection table, per-model prompt templates, and visual system prefix technique
4. **Derive the visual system prefix**: a 20-30 word shared style block from the visual brief's Color Palette + Image Direction. This prefix is appended to EVERY image prompt. Example:
   ```
   Warm natural light, soft directional shadows. Palette: cream #F5F0EB,
   sage green #87A878, terracotta #C67B5C. Clean minimal composition.
   Premium but approachable.
   ```
5. Extract RGB color values from the visual brief for Recraft models' `colors` API parameter
6. **(Issue #1077) Read `.runs/slot-intent.json`** if it exists. When `design_slots_enabled == true`, this file controls per-slot generation routing:
   - `production_method != "ai_generated"` (e.g., `dynamic_runtime` for og-photo when next/og emits opengraph-image.tsx; `none` for service/cli archetypes; `programmatic_css` / `svg_icon` for slots replaced by CSS) → **skip generation entirely** for that slot
   - `candidate_budget` → maps to candidates_per_slot (high=existing budget, medium≈3 explore + 1 exploit, low=1 explore + 0 exploit)
   - `slot_role` biases prompt construction: `texture` → minimal subject, abstract; `watermark` → vector-priority; `focal` → unchanged; `conditional` → defensive (still generate but design-critic will suppress regen via PR3 drift detector)

   Defensive behavior: if slot-intent.json is absent OR `design_slots_enabled` is false, ignore slot-intent and use legacy candidate budget (Phase 1/2 tables below). This preserves backward-compat for projects bootstrapped before PR1b.

   Quick check (run early):
   ```bash
   python3 - <<'PYEOF'
   import json, os
   slot_intent = None
   if os.path.exists(".runs/slot-intent.json"):
       d = json.load(open(".runs/slot-intent.json"))
       if d.get("design_slots_enabled"):
           slot_intent = d.get("slots", {})
   if slot_intent:
       skipped = [k for k, s in slot_intent.items()
                  if s.get("production_method") != "ai_generated"]
       print(f"slot-intent active; skipping non-AI slots: {skipped}")
   else:
       print("slot-intent inactive; using legacy budget")
   PYEOF
   ```

### Step 1b: Check image source strategy

Read `.runs/current-visual-brief.md` Image Direction → **Image source strategy** field.

- If `photography` or `mixed` with photography images:
  1. For each image marked for photography: use WebFetch (load via ToolSearch)
     to search `https://unsplash.com/s/photos/{search-terms}` with terms from
     the visual brief's Image Direction
  2. Select the most relevant photo, extract the photo ID from the page
  3. Download to `public/images/{filename}` via:
     ```bash
     curl -L "https://images.unsplash.com/photo-{ID}?auto=format&fit=crop&w={width}&q=80" \
       -o public/images/{filename}
     ```
  4. Self-evaluate the downloaded image (same 5 quality dimensions)
  5. Write manifest entry with `"source": "unsplash"` and `"unsplash_id": "{ID}"`

- If `illustration` or remaining AI-generated images in `mixed`:
  Continue with Steps 2-4 below (fal.ai generation)

### Step 1c: Create candidate staging directory

```bash
mkdir -p .runs/image-candidates
```

All candidate images are generated into `.runs/image-candidates/` first (not directly into `public/images/`). Only the winning candidate per slot is copied to `public/images/`.

### Step 2: Install packages
```bash
npm install @fal-ai/client
npm install --save-dev sharp
```

`sharp` is required for the dimension cap (see Dimension Contract below). It is a small (~10MB) image-processing library and is installed unconditionally because scaffold-images runs across archetypes (web-app / service / cli) whenever `image_gen_status: "available"` — it cannot rely on Next.js's transitive copy.

If the `sharp` install fails (no npm, offline, package unavailable): **stop and report**. Do NOT proceed with a silent skip — without the cap, oversized candidates will crash the downstream design-critic agent (see #957).

## Dimension Contract

Every image written to `public/images/` and `.runs/image-candidates/` MUST have a longest side ≤ **1920 px**. This matches the hero slot's natural Full HD dimension (1920×1080) and keeps ~80 px of margin below the 2000 px single-side limit that Claude's many-image vision pipeline enforces. A single oversized artifact causes downstream design-critic agents to crash mid-review, cascading the entire Phase-2 visual review into recovery traces.

To enforce this, every generation path in Step 4 must post-process its output with `sharp` before writing:

```ts
import sharp from "sharp";
await sharp(inputPath)
  .resize({ width: 1920, height: 1920, fit: "inside", withoutEnlargement: true })
  .toFile(outputPath);
```

- `fit: "inside"` preserves aspect ratio and fits within a 1920×1920 bounding box (hero 1920×1080 → unchanged; oversized 2400×1600 → 1920×1280).
- `withoutEnlargement: true` never upscales images that are already smaller than the cap.
- This applies to BOTH `.runs/image-candidates/*.webp` (used by design-critic Step 5.5) and final `public/images/*.webp`.

### Step 3: Create image generation library
Create `src/lib/image-gen.ts` following the multi-model code template in `.claude/stacks/images/fal.md`. The generator must call the `sharp` cap (above) on every write path — both intermediate candidate writes into `.runs/image-candidates/` and final writes into `public/images/`.

### Step 4: Generate candidates with explore-exploit feedback loop

For each image slot, generate candidates in two phases: **explore** (maximize diversity to find the right direction) then **exploit** (refine the winning direction). Candidates are stored in `.runs/image-candidates/`; only the winner is copied to `public/images/`.

**Phase 1 (EXPLORE) — maximize diversity, find the right direction:**

> **Slot-intent override (Issue #1077)**: when slot-intent is active (Step 1 #6) and a slot's `production_method != "ai_generated"`, **skip that row entirely** (do not generate, do not write a manifest entry). When `candidate_budget=low`, use 1 explore (AI only, no Unsplash). When `candidate_budget=medium`, halve the explore count rounded up. When `candidate_budget=high` or slot-intent inactive, use the table below as-is.

| # | Filename | Type | Model | Dimensions | Explore | Sources |
|---|----------|------|-------|-----------|---------|---------|
| 1 | `hero.webp` | hero | FLUX.2 Pro (+ GPT-2 alt) | 1920x1088 | 3 | 1 FLUX + 1 GPT-2 + 1 Unsplash |
| 2 | `feature-1.webp` | feature | Recraft V4 Pro | 800x608 | 2 | 1 AI + 1 Unsplash (ensemble anchor) |
| 3 | `feature-2.webp` | feature | Recraft V4 Pro | 800x608 | 2 | 1 AI + 1 Unsplash (style-match feature-1) |
| 4 | `feature-3.webp` | feature | Recraft V4 Pro | 800x608 | 2 | 1 AI + 1 Unsplash (style-match feature-1) |
| 5 | `logo.svg` | logo | Recraft V4 Vector | 512x512 | 3 | 3 AI variants (no Unsplash for logos) |
| 6 | `og-photo.png` | og | GPT Image 2 | 1200x640 | 2 | 1 AI + 1 Unsplash |
| 7 | `empty-state.webp` | empty-state | Recraft V4 Pro | 400x400 | 2 | 1 AI + 1 Unsplash |

**Phase 2 (EXPLOIT) — refine the winning direction with AI-only variants:**

| # | Filename | Exploit | Notes |
|---|----------|---------|-------|
| 1 | `hero.webp` | 3 AI | Highest-impact slot, most refinement |
| 2 | `feature-1.webp` | 1 AI | Ensemble anchor refinement |
| 3 | `feature-2.webp` | 1 AI | Style-matched to feature-1 |
| 4 | `feature-3.webp` | 1 AI | Style-matched to feature-1 |
| 5 | `logo.svg` | 2 AI | Brand mark precision |
| 6 | `og-photo.png` | 1 AI | Social sharing refinement |
| 7 | `empty-state.webp` | 0 | Low-frequency display — skip exploit |

**Execution order:** Process each slot sequentially — complete all three phases (explore → direction extraction → exploit → winner selection) for one slot before moving to the next. This is required because feature-1 must have a selected winner before feature-2/3 can begin (style anchor dependency). Process slots in table order (hero first, empty-state last).

#### Step 4.1 (EXPLORE) — diverse candidate generation

**For the current image slot:**

1. **Craft maximally diverse explore prompts.** Each AI candidate MUST vary on a DIFFERENT primary axis. Do not reuse the same axis within a slot:
   - **Subject framing**: aspirational lifestyle vs product in context vs abstract mood
   - **Composition**: centered subject vs rule-of-thirds vs wide establishing shot
   - **Emotional tone**: energetic vs calm vs professional vs playful
   - **Camera perspective**: eye-level vs overhead vs low-angle (for FLUX.2 Pro photorealism)
   
   Example for a fitness app hero (2 AI explore variants):
   - explore-1 (subject framing): "Woman mid-stride on a sunlit trail, golden hour backlight, rule-of-thirds, aspirational energy"
   - explore-2 (composition): "Aerial view of a runner on a coastal path, vast landscape, sense of freedom and possibility"
   
   All prompts share the visual system prefix for color/style consistency but MUST differ in primary axis.

   **Hero slot specifically** (Phase 1 table: 1 FLUX + 1 GPT-2 + 1 Unsplash):
   - The FLUX.2 Pro candidate prompt should focus on photographic mood, lighting, and human subject — FLUX's photorealism + JSON-structured prompt + HEX object-level color binding are its strengths
   - The GPT-Image-2 candidate prompt should include legible brand text, a UI element with text, or a poster/sign in-scene — GPT-2's ~99% text rendering is its differentiator (validated 2026-04-22 bakeoff)
   - This intentional FLUX-vs-GPT-2 split prevents the two AI candidates from collapsing into similar prompts. Design-critic picks the winner from page context during /verify.

2. **Generate AI explore candidates** into `.runs/image-candidates/`:
   ```bash
   npx tsx -e "
   import { generateImage } from './src/lib/image-gen';
   const result = await generateImage({
     type: '<image_type>',
     prompt: '<explore prompt variant>',
     width: <width>,
     height: <height>,
     filename: '<slot>-explore-<N>.webp',
     altText: '<descriptive alt text>',
     colors: [/* RGB from visual brief, for Recraft models */],
     outputDir: '.runs/image-candidates'
   });
   console.log(JSON.stringify(result));
   "
   ```

3. **Generate Unsplash explore candidates** (for slots with Unsplash budget in the Phase 1 table):
   - Use a DIFFERENT search query for each Unsplash candidate, emphasizing a different angle of the subject.
   - Use WebFetch (load via ToolSearch) for each search. Pick the single best photo from each search result page.
   - Using different search terms produces genuinely diverse candidates. Picking multiple photos from the same search produces similar-looking results — avoid this.
   - If WebFetch extraction fails for any search: reallocate that slot to an additional AI explore variant instead
   - Download each to `.runs/image-candidates/<slot>-explore-unsplash-<N>.webp`:
     ```bash
     curl -L "https://images.unsplash.com/photo-{ID}?auto=format&fit=crop&w={width}&q=80" \
       -o .runs/image-candidates/<slot>-explore-unsplash-<N>.webp
     ```

4. **View and score each explore candidate** using the Read tool:
   - Read `.runs/image-candidates/<slot>-explore-<N>.webp` to view
   - Self-evaluate against the 5 quality dimensions (subject, style, color, composition, polish)
   - Record scores for each candidate

#### Direction extraction (between explore and exploit)

**Skip this step for empty-state** (no exploit phase — proceed directly to winner selection from explore candidates).

After scoring all explore candidates for a slot, **derive the direction signal** for the exploit phase:

1. Identify the **top-2 scoring explore candidates** for this slot
2. Visually re-inspect both via the Read tool — look at the actual images, not just scores
3. Write a **direction signal** (15-20 words) that combines the strongest visual elements from the top-2: dominant color temperature, composition style, subject treatment, rendering technique, emotional register
4. Record the direction signal in the sidecar under the slot's metadata

This mechanism is identical to the feature ensemble style anchor — but applied per-slot rather than only to features. Example direction signal: "Aerial coastal perspective, warm golden hour, vast open composition, textured path detail, sense of freedom"

#### Step 4.2 (EXPLOIT) — direction-informed refinement

For each image slot with exploit budget (all except empty-state):

1. **Craft exploit prompts** that REFERENCE the direction signal. Each exploit prompt MUST:
   - Include specific visual elements named in the direction signal
   - Vary on SECONDARY axes only: lighting angle, material detail, perspective shift, edge treatment, depth of field
   - NOT change the primary direction (subject framing, composition style, emotional tone)
   
   Example for hero with direction signal "Aerial coastal perspective, warm golden hour, vast open composition, sense of freedom":
   - exploit-1 (lighting): "Aerial coastal path, late golden hour with long shadows, lens flare at horizon edge"
   - exploit-2 (detail): "Aerial coastal path, golden hour, textured sand and water detail, shallow depth tilt-shift"
   - exploit-3 (perspective): "Slightly lower aerial angle on coastal path, golden hour, runner small in frame, emphasizing scale"

2. **Generate AI exploit candidates** into `.runs/image-candidates/`:
   ```bash
   npx tsx -e "
   import { generateImage } from './src/lib/image-gen';
   const result = await generateImage({
     type: '<image_type>',
     prompt: '<exploit prompt — must reference direction signal>',
     width: <width>,
     height: <height>,
     filename: '<slot>-exploit-<N>.webp',
     altText: '<descriptive alt text>',
     colors: [/* RGB from visual brief, for Recraft models */],
     outputDir: '.runs/image-candidates'
   });
   console.log(JSON.stringify(result));
   "
   ```

3. **View and score each exploit candidate** using the Read tool (same 5 dimensions)

3.5. **Write provenance JSON sidecar (#1272 hard-block contract).** For each candidate generated in Steps 4.1-4.2, write a sibling `<candidate-path>.provenance.json` capturing the generation parameters BEFORE the design-critic confirmation pass needs them:
   ```bash
   # In Node script that called generateImage(), capture and write:
   const fs = require('fs');
   const provenance = {
     model: result.model,                    // e.g. "fal-ai/flux-2-pro"
     prompt: prompt_text,                    // the actual prompt sent
     prompt_hash: require('crypto').createHash('sha256').update(prompt_text).digest('hex').slice(0, 16),
     seed: result.seed || null,              // when fal returns a seed
     generated_at: new Date().toISOString(),
   };
   fs.writeFileSync(
     `.runs/image-candidates/<slot>-<phase>-<N>.provenance.json`,
     JSON.stringify(provenance, null, 2)
   );
   ```
   Why this matters: design-critic Step 5.5's hard-block validator
   (`.claude/scripts/validate-step55-evidence.py`) joins evidence screenshots
   with provenance triples and asserts UNIQUE `(model, prompt_hash, seed)` per
   candidate set. Without provenance written at generation time, the validator
   cannot distinguish "agent rendered N distinct images" from "agent labeled
   the same image as N candidates with rotated metadata" (round-2 critic
   Concern 1). Pixel-only perceptual hash is bypassable by trivial transforms;
   provenance binding is the load-bearing check.

4. **Select the winner across BOTH phases.** Compare all explore AND exploit candidates for this slot, pick the highest-scoring one. Copy it to the canonical path:
   ```bash
   cp .runs/image-candidates/<winning-file> public/images/<canonical-filename>
   ```

5. **Feature ensemble selection** (feature-2 and feature-3 only):
   After selecting the feature-1 winner, derive a **style anchor prefix** from it — describe its visual characteristics (illustration style, color temperature, abstraction level, rendering technique) in 15-20 words. When generating feature-2 and feature-3 candidates (both explore AND exploit), prepend this style anchor prefix to every prompt. This ensures cross-feature consistency while still allowing per-feature subject diversity.

6. If the specialized model fails entirely, the `generateImage()` function automatically falls back to FLUX.2 Pro, then to SVG placeholder. Continue with the next slot.

7. **SVG post-processing (logo slot only):**
   After generating each SVG logo candidate, read the SVG source and remove any opaque white/near-white background rectangle that Recraft V4 Vector commonly adds:
   ```bash
   # Remove rect elements with white fill (common Recraft V4 Vector artifact)
   sed -i '' '/<rect[^>]*fill="\(#[Ff][Ff][Ff]\|#[Ff][Ff][Ff][Ff][Ff][Ff]\|white\)"[^>]*\/\?>/d' .runs/image-candidates/<logo-file>.svg
   ```
   After removal, verify the SVG still contains at least one visible path element and renders correctly by reading it with the Read tool. If the background rect was part of an intentional design element (the SVG looks broken after removal), restore the original and note the issue — the design-critic Layer 1 SVG transparency check will catch it in context.

### Step 4.3: Completeness Check

Before writing the manifest, verify the **expected** images from the Phase 1 table exist on disk:

1. Count expected images. When slot-intent is active and `design_slots_enabled` is true, expected count = number of slots with `production_method == "ai_generated"`. When slot-intent is inactive, expected count = 7 (full Phase 1 table).
2. For each row in the table whose slot is NOT skipped by slot-intent, verify the filename exists in `public/images/`. The full default list is: `hero.webp`, `feature-1.webp`, `feature-2.webp`, `feature-3.webp`, `logo.svg`, `og-photo.png`, `empty-state.webp`.
3. If any expected image is missing, generate it now using the same explore-exploit cycle from Steps 4.1-4.2 before proceeding.

Do NOT proceed to Step 5 until all expected images are present on disk.

### Step 5: Write manifest
Write `.runs/image-manifest.json`:
```json
{
  "status": "complete",
  "fallback": false,
  "images": [
    {
      "filename": "<actual filename>",
      "publicPath": "/images/<actual filename>",
      "altText": "<descriptive alt text>",
      "width": <width>,
      "height": <height>,
      "fallback": <true if SVG placeholder>,
      "model": "<model ID used>",
      "source": "<fal | unsplash | placeholder>",
      "unsplash_id": "<photo ID if source is unsplash, null otherwise>",
      "score": {
        "subject": <1-10>,
        "style": <1-10>,
        "color": <1-10>,
        "composition": <1-10>,
        "polish": <1-10>
      },
      "retries": <number of retries across all sources>
    }
  ]
}
```
Set `"fallback": true` at top level if ALL images fell back to SVG.

### Step 5b: Write candidate sidecar

Write `.runs/image-candidates.json` with metadata for ALL candidates generated (winners and runners-up). **Stamp `"schema_version": 2` on first write — scaffold-images is the canonical birthplace per #1272 follow-up. Closes the back door where downstream agents that skip Step 5.5 also skip the version stamp, silently grandfathering the unstamped sidecar past validate-step55-evidence.py.**

```json
{
  "schema_version": 2,
  "generated_at": "<ISO 8601>",
  "strategy": "explore-exploit",
  "total_candidates": <total across all slots>,
  "slots": {
    "hero": {
      "candidates": [
        {
          "path": ".runs/image-candidates/hero-explore-1.webp",
          "source": "fal",
          "model": "fal-ai/flux-2-pro",
          "phase": "explore",
          "prompt_variant": "<short description of prompt focus>",
          "score": { "subject": <1-10>, "style": <1-10>, "color": <1-10>, "composition": <1-10>, "polish": <1-10> },
          "selected": false
        },
        {
          "path": ".runs/image-candidates/hero-explore-unsplash-1.webp",
          "source": "unsplash",
          "unsplash_id": "<photo ID>",
          "phase": "explore",
          "score": { "subject": <1-10>, "style": <1-10>, "color": <1-10>, "composition": <1-10>, "polish": <1-10> },
          "selected": false
        },
        {
          "path": ".runs/image-candidates/hero-exploit-1.webp",
          "source": "fal",
          "model": "fal-ai/flux-2-pro",
          "phase": "exploit",
          "prompt_variant": "<refinement of winning direction>",
          "score": { "subject": <1-10>, "style": <1-10>, "color": <1-10>, "composition": <1-10>, "polish": <1-10> },
          "selected": true
        }
      ],
      "winner_index": 2,
      "direction_signal": "<15-20 word description of winning visual direction>"
    },
    "feature-1": {
      "candidates": ["..."],
      "winner_index": 0,
      "ensemble_anchor": true,
      "direction_signal": "<direction signal>"
    },
    "feature-2": {
      "candidates": ["..."],
      "winner_index": 0,
      "style_matched_to": "feature-1",
      "direction_signal": "<direction signal>"
    },
    "feature-3": {
      "candidates": ["..."],
      "winner_index": 0,
      "style_matched_to": "feature-1",
      "direction_signal": "<direction signal>"
    },
    "logo": { "candidates": ["..."], "winner_index": 0, "direction_signal": "<direction signal>" },
    "og-photo": { "candidates": ["..."], "winner_index": 0, "direction_signal": "<direction signal>" },
    "empty-state": { "candidates": ["..."], "winner_index": 0, "direction_signal": null }
  }
}
```

The sidecar is consumed by the design-critic agent during `/verify`. If the design-critic finds the winner unsuitable in page context, it can try alternate candidates from this pool before regenerating from scratch.

### Step 6: Write trace via the canonical AOC v1.1 writer

The writer stamps `agent`, `timestamp`, `status:"completed"`, `provenance:"self"`, `partial:false`, `run_id`, `skill`, `spawn_sha`, and `spawn_index` from active identity + spawn-log. Domain-specific fields below merge through the writer's payload-passthrough.

```bash
python3 - <<'PYEOF'
import json, subprocess
trace = {
    "verdict": "pass",
    "result": "clean",
    "checks_performed": ["candidates_generated", "self_scored", "winners_copied", "sidecar_written"],
    "no_fixes_claimed": True,
    "files_created": ["public/images/hero.webp", "..."],
    "issues": [],
    "image_count": 7,
    "fallback_count": 0,
    "total_candidates": "<total across all slots>",
    "candidates_per_slot": {"hero": 6, "feature-1": 3, "feature-2": 3, "feature-3": 3, "logo": 5, "og-photo": 3, "empty-state": 2},
    "phases_executed": ["explore", "exploit"],
    "explore_candidates_count": 16,
    "exploit_candidates_count": 9,
    "direction_signals": {"hero": "<signal>", "feature-1": "<signal>", "feature-2": "<signal>", "feature-3": "<signal>", "logo": "<signal>", "og-photo": "<signal>", "empty-state": None},
    "weakest_image": "<filename>",
    "weakest_score": "<min score across all dimensions and images>",
    "total_retries": "<sum of retries across all images>",
    "models_used": ["fal-ai/flux-2-pro", "fal-ai/recraft/v4/pro/text-to-image", "..."],
}
subprocess.run(
    ["bash", ".claude/scripts/write-agent-trace.sh", "scaffold-images",
     "--json", json.dumps(trace)],
    check=True,
)
PYEOF
```
