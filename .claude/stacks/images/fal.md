---
assumes: [framework/nextjs]
packages:
  runtime: ["@fal-ai/client"]
  dev: []
files:
  - src/lib/image-gen.ts
env:
  server: [FAL_KEY]
  client: []
ci_placeholders:
  FAL_KEY: placeholder-fal-key
clean:
  files: []
  dirs: [public/images]
gitignore: []
---
# Images: fal.ai (Multi-Model)
> Template infrastructure -- used during bootstrap image generation.
> Not gated by experiment.yaml stack. Activated when `FAL_KEY` is available.
> **Do not register** `images` in archetypes `optional_stacks`, `SHARED_STACK_KEYS`,
> or other category registration points -- this is internal infrastructure, not a
> user-declared stack category.
> Single `FAL_KEY` drives 5 specialized models for world-champion image quality.

## Packages
```bash
npm install @fal-ai/client
```

## Model Selection Strategy

Each image type uses the optimal model. All models share one `FAL_KEY` via fal.ai.

| Image Type | Model | fal.ai Model ID | Why |
|-----------|-------|-----------------|-----|
| Hero (photography) | FLUX.2 Pro | `fal-ai/flux-2-pro` | Best photorealism, JSON prompts, HEX colors |
| Feature illustrations | Recraft V4 Pro | `fal-ai/recraft/v4/pro/text-to-image` | Native design taste, RGB color control |
| Logo (SVG) | Recraft V4 Vector | `fal-ai/recraft/v4/pro/text-to-vector` | Only model producing native SVG paths |
| OG/Social (with text) | GPT Image 2 | `fal-ai/gpt-image-2` | ~99% text rendering accuracy (validated 2026-04-22 bakeoff) |
| Product mockup | GPT Image 2 | `fal-ai/gpt-image-2` | True alpha via prompt, perfect spelling (validated 2026-04-22 bakeoff) |
| Empty state | Recraft V4 Pro | `fal-ai/recraft/v4/pro/text-to-image` | Design taste for friendly illustrations |

**Fallback chain:** Specialized model fails → retry with FLUX.2 Pro → SVG placeholder.

## Files to Create

### `src/lib/image-gen.ts` -- Multi-model AI image generation with fal.ai
```ts
import { fal } from "@fal-ai/client";
import { writeFile, mkdir } from "fs/promises";
import { existsSync, readFileSync } from "fs";
import { join } from "path";
import { homedir } from "os";

const MAX_RETRIES = 2;
const BASE_DELAY_MS = 2000;
const PUBLIC_IMAGES_DIR = join(process.cwd(), "public", "images");

const FALLBACK_MODEL = "fal-ai/flux-2-pro";

// --- Model Configuration ---

export type ImageType = "hero" | "feature" | "logo" | "og" | "mockup" | "empty-state";

interface ModelConfig {
  modelId: string;
  defaultParams: Record<string, unknown>;
  outputFormat: "jpeg" | "png" | "webp" | "svg";
}

const MODEL_CONFIGS: Record<ImageType, ModelConfig> = {
  hero: {
    modelId: "fal-ai/flux-2-pro",
    defaultParams: { output_format: "jpeg", safety_tolerance: "2" },
    outputFormat: "jpeg",
  },
  feature: {
    modelId: "fal-ai/recraft/v4/pro/text-to-image",
    defaultParams: {},
    outputFormat: "webp",
  },
  logo: {
    modelId: "fal-ai/recraft/v4/pro/text-to-vector",
    defaultParams: {},
    outputFormat: "svg",
  },
  og: {
    modelId: "fal-ai/gpt-image-2",
    defaultParams: { quality: "high", output_format: "png" },
    outputFormat: "png",
  },
  mockup: {
    modelId: "fal-ai/gpt-image-2",
    defaultParams: { quality: "high", output_format: "png" },
    outputFormat: "png",
  },
  "empty-state": {
    modelId: "fal-ai/recraft/v4/pro/text-to-image",
    defaultParams: {},
    outputFormat: "webp",
  },
};

// --- Types ---

export interface GenerateImageOptions {
  type: ImageType;
  prompt: string;
  width: number;
  height: number;
  filename: string;
  altText: string;
  colors?: Array<{ r: number; g: number; b: number }>; // For Recraft models
  outputDir?: string; // Override output directory (default: public/images). Used for multi-candidate generation to write to .runs/image-candidates/
}

export interface ImageResult {
  path: string;
  publicPath: string;
  altText: string;
  fallback: boolean;
  model: string;
}

// --- Internal ---

function isDemoMode(): boolean {
  if (process.env.DEMO_MODE === "true") return true;
  if (process.env.FAL_KEY) return false;
  // Check persistent key file (matches bootstrap preflight detection in state-8)
  try {
    const keyPath = join(homedir(), '.fal', 'key');
    const key = readFileSync(keyPath, 'utf-8').trim();
    if (key && !key.startsWith('placeholder')) {
      process.env.FAL_KEY = key; // Bridge to env var for fal client
      return false;
    }
  } catch { /* ~/.fal/key not readable */ }
  return true;
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function ensureDir(dir: string = PUBLIC_IMAGES_DIR): Promise<void> {
  if (!existsSync(dir)) {
    await mkdir(dir, { recursive: true });
  }
}

async function callModel(
  modelId: string,
  input: Record<string, unknown>
): Promise<string> {
  const result = await fal.subscribe(modelId, { input });
  const data = result.data as { images?: { url: string }[] };
  const url = data.images?.[0]?.url;
  if (!url) throw new Error(`No image URL from ${modelId}`);
  return url;
}

async function downloadToFile(url: string, filePath: string): Promise<void> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Download failed: ${response.status}`);
  const buffer = Buffer.from(await response.arrayBuffer());
  await writeFile(filePath, buffer);
}

// --- Public API ---

/**
 * Generate an image using the optimal model for the image type.
 * Falls back to FLUX.2 Pro if the specialized model fails,
 * then to SVG placeholder if all API calls fail.
 */
export async function generateImage(
  options: GenerateImageOptions
): Promise<ImageResult> {
  const { type, prompt, width, height, filename, altText, colors, outputDir } = options;
  const config = MODEL_CONFIGS[type];
  const targetDir = outputDir ?? PUBLIC_IMAGES_DIR;
  const filePath = join(targetDir, filename);
  const publicPath = outputDir ? `${outputDir}/${filename}` : `/images/${filename}`;

  await ensureDir(targetDir);

  if (isDemoMode()) {
    return generateSvgPlaceholder({ width, height, filename, altText });
  }

  // Build model-specific input
  const input: Record<string, unknown> = {
    prompt,
    ...config.defaultParams,
  };

  // Align to 16-pixel multiples (required by GPT-Image-2; harmless for other models)
  const alignedW = Math.round(width / 16) * 16;
  const alignedH = Math.round(height / 16) * 16;
  input.image_size = { width: alignedW, height: alignedH };

  // Recraft color support
  if (colors && config.modelId.includes("recraft")) {
    input.colors = colors;
  }

  // Try specialized model, then fallback to FLUX, then SVG
  const modelsToTry = config.modelId === FALLBACK_MODEL
    ? [config.modelId]
    : [config.modelId, FALLBACK_MODEL];

  for (const modelId of modelsToTry) {
    const modelInput = modelId === FALLBACK_MODEL && modelId !== config.modelId
      ? { prompt, image_size: { width, height }, output_format: "jpeg", safety_tolerance: "2" }
      : input;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        const imageUrl = await callModel(modelId, modelInput);
        await downloadToFile(imageUrl, filePath);
        return { path: filePath, publicPath, altText, fallback: false, model: modelId };
      } catch (error) {
        if (attempt < MAX_RETRIES) {
          await sleep(BASE_DELAY_MS * Math.pow(2, attempt));
        } else if (modelId !== FALLBACK_MODEL) {
          console.warn(`${modelId} failed for ${filename}, trying fallback...`);
          break; // Move to fallback model
        }
      }
    }
  }

  console.warn(`All models failed for ${filename}, using SVG placeholder`);
  return generateSvgPlaceholder({ width, height, filename, altText });
}

/**
 * Generate a themed SVG placeholder at the same file path.
 */
export async function generateSvgPlaceholder(options: {
  width: number;
  height: number;
  filename: string;
  altText: string;
}): Promise<ImageResult> {
  const { width, height, filename, altText } = options;
  const svgFilename = filename.replace(/\.\w+$/, ".svg");
  const filePath = join(PUBLIC_IMAGES_DIR, svgFilename);
  const publicPath = `/images/${svgFilename}`;

  await ensureDir();

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:hsl(var(--primary, 220 70% 50%));stop-opacity:0.15"/>
      <stop offset="100%" style="stop-color:hsl(var(--primary, 220 70% 50%));stop-opacity:0.05"/>
    </linearGradient>
  </defs>
  <rect width="${width}" height="${height}" fill="url(#bg)"/>
  <circle cx="${width * 0.3}" cy="${height * 0.4}" r="${Math.min(width, height) * 0.15}" fill="hsl(var(--primary, 220 70% 50%))" opacity="0.1"/>
  <circle cx="${width * 0.7}" cy="${height * 0.6}" r="${Math.min(width, height) * 0.2}" fill="hsl(var(--primary, 220 70% 50%))" opacity="0.08"/>
</svg>`;

  await writeFile(filePath, svg, "utf-8");
  return { path: filePath, publicPath, altText, fallback: true, model: "svg-placeholder" };
}
```

## Image File Path Contract

| Path | Purpose | Dimensions | Model |
|------|---------|-----------|-------|
| `public/images/hero.webp` (or `.svg`) | Landing page hero | 1920x1088 | FLUX.2 Pro (+ GPT-2 alt) |
| `public/images/feature-1.webp` (or `.svg`) | Feature section 1 | 800x608 | Recraft V4 Pro |
| `public/images/feature-2.webp` (or `.svg`) | Feature section 2 | 800x608 | Recraft V4 Pro |
| `public/images/feature-3.webp` (or `.svg`) | Feature section 3 | 800x608 | Recraft V4 Pro |
| `public/images/logo.svg` | Brand logo icon | 512x512 | Recraft V4 Vector |
| `public/images/og-photo.png` (or `.svg`) | OG social share image | 1200x640 | GPT Image 2 |
| `public/images/empty-state.webp` (or `.svg`) | Empty state illustration | 400x400 | Recraft V4 Pro |

The image manifest (`.runs/image-manifest.json`) records actual filenames and models used.

## Image Manifest

Written to `.runs/image-manifest.json` after generation:
```json
{
  "status": "complete",
  "fallback": false,
  "images": [
    {
      "filename": "hero.webp",
      "publicPath": "/images/hero.webp",
      "altText": "...",
      "width": 1920,
      "height": 1080,
      "fallback": false,
      "model": "fal-ai/flux-2-pro",
      "score": { "subject": 9, "style": 8, "color": 9, "composition": 8, "polish": 9 }
    }
  ]
}
```

## Multi-Candidate Usage

The `outputDir` option enables the **Explore-Exploit** architecture. Instead
of writing directly to `public/images/`, candidates are written to a staging
directory for comparison and selection.

**Generating a candidate:**
```ts
const result = await generateImage({
  type: "hero",
  prompt: "...",
  width: 1920, height: 1080,
  filename: "hero-explore-1.webp",
  altText: "...",
  outputDir: ".runs/image-candidates"
});
// result.path = ".runs/image-candidates/hero-explore-1.webp"
```

**Selecting a winner:** After scoring all candidates across both explore and
exploit phases, copy the winner to the canonical path:
```bash
cp .runs/image-candidates/hero-exploit-2.webp public/images/hero.webp
```

**Sidecar file:** All candidate metadata is recorded in `.runs/image-candidates.json`
(separate from the main `.runs/image-manifest.json`). See
`.claude/procedures/scaffold-images.md` Step 5b for the sidecar schema.

**Backwards compatibility:** When `outputDir` is omitted, behavior is identical
to the original single-candidate flow. The main manifest schema is unchanged.

## Model Documentation

### FLUX.2 Pro — Hero images, lifestyle photography
- **Model ID**: `fal-ai/flux-2-pro`
- **ELO**: ~1265 on LM Arena (tied #1 for photorealism)
- **Key params**: `image_size` (named enum or `{width, height}`), `output_format`, `safety_tolerance`
- **No negative prompts** — describe what you want, not what to avoid
- **Supports JSON structured prompts** for complex multi-element scenes
- **HEX colors**: Associate with specific objects: `"car is #FF0000"`, not `"use #FF0000"`

### Recraft V4 Pro — Feature illustrations, empty states
- **Model ID**: `fal-ai/recraft/v4/pro/text-to-image`
- **Key params**: `colors` (RGB array for brand color control), `background_color`
- **No `style` API param for V4** — describe style entirely in prompt
- **Native design taste** — compositions feel intentional, not stock-like
- **Output**: WebP

### Recraft V4 Vector — Logo SVGs
- **Model ID**: `fal-ai/recraft/v4/pro/text-to-vector`
- **Output**: Real SVG (`image/svg+xml`) with clean vector paths
- **Key params**: `colors` (RGB array), `background_color` (null for transparent)
- **Best with constraint-driven prompts**: "flat colors only, no gradients, no shadows"

### GPT Image 2 — OG cards, ad creative (text-heavy) — PRIMARY for og + mockup
- **Model ID**: `fal-ai/gpt-image-2`
- **~99% text rendering accuracy** — validated via 2026-04-22 bakeoff (only model to achieve 60/60 on og-photo slot)
- **Key params**: `quality: "high"`, `output_format: "png"`
- **Image size**: custom `{ width, height }` with **16-pixel-multiple constraint**, max 3840px/edge
- **Strengths**: Pixel-perfect typography across small fonts, dense paragraphs, multilingual layouts
- **Transparent background**: triggered via prompt phrase (e.g., `"transparent background outside the panel"`); no API param needed — verified true alpha output in bakeoff
- **Edit endpoint**: `fal-ai/gpt-image-2/edit` accepts `image_urls` + optional `mask_image_url` for in-place refinement
- **Prompt style**: Prose description with explicit color hex codes and font weight; no special enum params

### Ideogram V3 — Alternative for OG (kept for reference, not default)
- **Model ID**: `fal-ai/ideogram/v3`
- **~90% text rendering accuracy** — observed 3 visible errors on small typography during bakeoff
- **Key params**: `style: "DESIGN"`, `expand_prompt: false`, `rendering_speed: "QUALITY"`, `negative_prompt`
- May be revisited if GPT-Image-2 cost becomes a concern (~$0.13 cheaper per og image)

### GPT Image 1.5 — Alternative for mockup (kept for reference, not default)
- **Model ID**: `fal-ai/gpt-image-1.5`
- Has explicit `background: "transparent"` param but produced spelling errors in bakeoff
- 32,000 char prompt limit — far longer than any other model
- May be revisited for cost reasons (GPT-2 is +65% per image: $0.13 → $0.22 high quality)

## Prompt Engineering Patterns

### Visual System Prefix

Derive a 20-30 word shared style block from the visual brief's **Color Palette** and **Image Direction** sections. Prepend or append this to EVERY image prompt to maintain cross-image visual consistency.

Example:
```
Warm natural light, soft directional shadows. Palette: cream #F5F0EB,
sage green #87A878, terracotta #C67B5C, charcoal #2D2D2D.
Clean minimal composition. Premium but approachable.
```

This prefix is NOT a new artifact — it is a formatting technique applied to existing Image Direction content.

### Per-Model Prompt Templates

**FLUX.2 Pro (hero images) — 30-80 words, subject-first, photography language:**
```
{Detailed subject description}. {Environment and scene context}.
{Lighting: direction, quality, temperature}. {Composition: angle, framing, negative space for text overlay}.
Shot on {camera}, {focal length} lens, {aperture}. {Visual System Prefix}.
```

Example:
```
Premium wireless headphone resting on weathered oak desk, soft morning light
filtering through linen curtains from the left, shallow depth of field, warm
amber tones. Shot on Sony A7IV, 85mm lens, f/1.8. Lifestyle editorial
photography, clean and aspirational. Palette: cream #F5F0EB, sage #87A878.
```

**Recraft V4 Pro (feature illustrations) — design-director language, format context:**
```
{Output format: feature illustration for a SaaS landing page}.
{Core concept and subject}. {Background/environment}. {Style: bold flat / editorial ink / geometric minimal}.
{Line behavior: clean strokes, consistent weight}. {Color logic: flat colors only, limited palette}.
{Mood and composition}. {Dimensions context: landscape 16:9}.
```
API: `colors: [{r:X, g:Y, b:Z}, ...]` from visual brief palette

**Recraft V4 Vector (logo) — constraint-driven, minimal:**
```
{Graphic type: geometric logo mark / abstract symbol / letterform}.
{Shape description and visual metaphor}. {Symmetry: radial/bilateral/asymmetric}.
Flat colors only, no gradients, no shadows, no texture. Strong silhouette,
readable at 16px favicon size. {Color count: 2-3 colors on transparent background}.
```
API: `colors: [{r:X, g:Y, b:Z}, ...]`, `background_color: null`

**GPT Image 2 (OG/social cards) — text-first, prose with explicit typography:**
```
Professional social media card design. {Background description with HEX color}.
Large bold "{HEADLINE TEXT}" in {color hex} {sans-serif/serif} {weight}, {position}.
{Subtext in lighter weight}. {Visual elements with brand colors}. Clean editorial layout, generous margins.
```
API: `quality: "high"`, `output_format: "png"`. No `style` enum or `expand_prompt` flag — GPT-2 reads natural-language style direction directly.

**GPT Image 2 (product mockups) — Background→Subject→Details→Constraints:**
```
{Scene/background setup}. {Product subject in detail: materials, colors, state}.
{Lighting: studio lighting from upper left, soft shadows}. {Camera angle and framing}.
{Visual System Prefix}. Transparent background outside the {panel/window/object}.
No watermark. No extra text. No background clutter.
```
API: `quality: "high"`, `output_format: "png"`. Transparent BG triggered via the prompt phrase (`"transparent background outside the X"`), no API param needed.

**Recraft V4 Pro (empty states) — friendly, encouraging:**
```
Friendly minimal illustration for an empty {context} state in a web application.
{Emotional subject: person looking curious / empty box with sparkles / open door with light}.
{Style: same as feature illustrations}. Encouraging and welcoming mood.
Simple clean design, centered composition, square format.
```
API: `colors` matching feature illustration palette

## Environment Variables
```
FAL_KEY=fal-...
```

## Security
- `FAL_KEY` is server-only -- never expose to client
- Image generation runs during bootstrap (build time) and design-critic (verify time), not at user request time
- No user input reaches image generation prompts -- prompts derive from experiment.yaml and visual brief only

## Demo Mode
When `DEMO_MODE=true` or `FAL_KEY` is not available, all calls return SVG placeholders without hitting the API. This enables visual review and CI builds without credentials. `FAL_KEY` is resolved from: (1) `process.env.FAL_KEY`, then (2) `~/.fal/key` persistent file. The first successful source is bridged to `process.env.FAL_KEY` for the fal SDK.

## PR Instructions
- After merging, set `FAL_KEY` via any of these methods:
  - `export FAL_KEY=fal-...` in your shell or add to `.env.local`
  - Or use the fal CLI (`~/.fal/key` is auto-detected)
  - Get your key from [fal.ai](https://fal.ai) > Dashboard > Keys
- For deployment: set `FAL_KEY` in your hosting provider's environment variables

## tsconfig.json exclude for `scripts/bakeoff/`

When a bakeoff subdirectory is scaffolded under `scripts/bakeoff/` (has its own `package.json` + `@fal-ai/client` dependency), it MUST be added to the root `tsconfig.json` `exclude` array. The default root `tsconfig.json` from `.claude/stacks/framework/nextjs.md` has `include: ["**/*.ts", "**/*.tsx", ...]` which picks up `scripts/bakeoff/*.ts`, but the root `node_modules` does not contain `@fal-ai/client` (that dep lives only in `scripts/bakeoff/package.json`). Result: `npm run build` type-check fails with `Cannot find module '@fal-ai/client'`.

**Required change to root `tsconfig.json` when `scripts/bakeoff/` is present:**

```json
{
  "compilerOptions": { ... },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules", ".next", ".runs", "scripts/bakeoff"]
}
```

This is fal-stack-local guidance — the root `tsconfig.json` in `nextjs.md` stays unconditional. Apply this exclude extension at the same time the bakeoff subdir + its `package.json` are scaffolded (see `.claude/procedures/scaffold-images.md`). Alternative: scaffold a scoped `tsconfig.json` inside `scripts/bakeoff/` — either approach resolves the build failure, but the root `exclude` is smaller-diff and matches the existing single-tsconfig convention.
  - Images are generated at bootstrap time and committed as static assets
  - The deployed app does NOT need `FAL_KEY` at runtime

## Stack Knowledge

```yaml
id: fal-sidecar-consumer-verify-semantic-value
maturity: raw
anti_pattern: false
composite_identity:
  root_cause_class: agent procedure prose unenforced — VERIFY checks key existence not semantic value
  divergence_pattern: validator-gap-semantic-value
  stack_scope: images/fal
composite_identity_hash: 091e1955a241
symptom_keywords: [candidates_tried, sidecar, design-critic, step-5.5, verify-gate]
fix_template: |
  When a state VERIFY enforces an agent contract on a sidecar-consuming agent
  (e.g., design-critic vs .runs/image-candidates.json), the assertion MUST
  validate the field's SEMANTIC VALUE against the sidecar's data, not just
  the field's PRESENCE. Pattern:
    1. Read sidecar with try/except (corrupt sidecar must not crash the gate)
    2. Compute expected_work from sidecar (e.g., unused candidate count for owned slots)
    3. Skip enforcement when trace is self-degraded with recovery_validated=True
    4. Assert agent emitted (work-done > 0) OR (escape-hatch field populated)
    5. On failure, name the original issue + regression lineage in the message
  Edit registry-owned VERIFY blocks at .claude/patterns/state-registry.json then run
  `make sync-verify` to propagate to .claude/skills/<skill>/state-N-*.md.
prevention_mechanism: validator
confidence_score: 0.7
occurrence_count: 1
linked_issues: [1129]
first_seen: 2026-04-28
last_seen: 2026-04-28
graduated_to: null
```

When a state VERIFY enforces an agent contract whose work depends on data in a
sidecar file (e.g., design-critic Step 5.5 confirmation pass against
`.runs/image-candidates.json`), check the field's semantic value, not just its
presence. The presence check is satisfied by an agent that emits the field
with a default value (e.g., `candidates_tried: 0`) without doing the work; the
semantic check ties the field to evidence in the sidecar. Always include an
escape hatch (`unresolved_images` or equivalent) for legitimate "could not do
the work" cases, plus a self-degraded fallback (`provenance="self-degraded"
AND recovery_validated=True`) for sanctioned recovery paths. See #1129
(regression of #1076) for the canonical case study: prose-only fix to the
procedure file regressed within days because no machine gate enforced it.
