import { fal } from "@fal-ai/client";
import { writeFile, mkdir } from "fs/promises";
import { existsSync, readFileSync } from "fs";
import { join, resolve } from "path";
import { homedir } from "os";

// ---------- FAL_KEY resolution ----------
function resolveFalKey(): string {
  if (process.env.FAL_KEY) return process.env.FAL_KEY;
  try {
    const k = readFileSync(join(homedir(), ".fal", "key"), "utf-8").trim();
    if (k) return k;
  } catch {}
  throw new Error("FAL_KEY not found in env or ~/.fal/key");
}
const FAL_KEY = resolveFalKey();
fal.config({ credentials: FAL_KEY });

// ---------- Output paths ----------
const REPO_ROOT = resolve(process.cwd(), "../..");
const OUTPUT_ROOT = join(REPO_ROOT, ".runs/model-bakeoff");
const IMAGES_DIR = join(OUTPUT_ROOT, "images");

// ---------- Scenario: Inkwell ----------
const BRAND = {
  name: "Inkwell",
  tagline: "Write 10× faster, sound like you",
  description: "AI email copilot — drafts replies in your voice, calibrates tone as you type, surfaces context from past threads",
  colors: {
    primary: { hex: "#2D4A7C", rgb: { r: 45, g: 74, b: 124 }, name: "deep navy" },
    accent:  { hex: "#E8A87C", rgb: { r: 232, g: 168, b: 124 }, name: "warm orange" },
    cream:   { hex: "#F5F0EB", rgb: { r: 245, g: 240, b: 235 }, name: "cream" },
    charcoal:{ hex: "#2D2D2D", rgb: { r: 45, g: 45, b: 45 }, name: "charcoal" }
  },
  visualPrefix: "Soft natural light, calm focused mood. Palette: deep navy #2D4A7C, warm orange #E8A87C, cream #F5F0EB, charcoal #2D2D2D. Clean modern composition. Premium SaaS aesthetic.",
  features: [
    { id: "feature-1", title: "Drafts in your voice", concept: "AI assistant analyzing past emails and writing in user's personal tone, abstract representation of voice/style being learned" },
    { id: "feature-2", title: "Tone calibration", concept: "A slider or dial control adjusting between formal, friendly, and concise communication styles" },
    { id: "feature-3", title: "Context surfacing", concept: "Past email threads being intelligently connected and surfaced as relevant context, like memory threads being woven together" }
  ]
};

// ---------- Sized slots (all dims aligned to 16-pixel multiples for GPT-2 compat) ----------
type Slot = "hero" | "feature-1" | "feature-2" | "feature-3" | "logo" | "og" | "mockup" | "empty-state";
const SLOT_SIZES: Record<Slot, { width: number; height: number }> = {
  "hero":        { width: 1920, height: 1088 },
  "feature-1":   { width: 800,  height: 608 },
  "feature-2":   { width: 800,  height: 608 },
  "feature-3":   { width: 800,  height: 608 },
  "logo":        { width: 512,  height: 512 },
  "og":          { width: 1200, height: 640 },
  "mockup":      { width: 1024, height: 1024 },
  "empty-state": { width: 400,  height: 400 }
};

// ---------- Aspect ratio mapping for nano-banana-pro ----------
function widthHeightToAspect(w: number, h: number): string {
  const r = w / h;
  const candidates: Array<[string, number]> = [
    ["21:9", 21/9], ["16:9", 16/9], ["3:2", 3/2], ["4:3", 4/3], ["5:4", 5/4],
    ["1:1", 1], ["4:5", 4/5], ["3:4", 3/4], ["2:3", 2/3], ["9:16", 9/16]
  ];
  let best = candidates[0]; let bestErr = Math.abs(r - best[1]);
  for (const c of candidates) {
    const e = Math.abs(r - c[1]);
    if (e < bestErr) { best = c; bestErr = e; }
  }
  return best[0];
}

// ---------- Prompt templates per slot ----------
const PROMPTS: Record<Slot, Array<{ id: string; text: (extra: string) => string }>> = {
  "hero": [
    {
      id: "v1-lifestyle",
      text: (extra) => `A focused professional at a clean wood desk in soft morning light, looking at a laptop screen with a calm satisfied expression. Warm natural light from the left through linen curtains. Shallow depth of field. Shot on Sony A7IV, 85mm lens, f/1.8. Lifestyle editorial photography for an AI email tool called Inkwell. ${extra}`
    },
    {
      id: "v2-conceptual",
      text: (extra) => `Aerial overhead view of a modern minimal desk: open laptop, a single ceramic mug, a small inkwell with a vintage fountain pen beside it, warm afternoon light casting long shadows. Negative space top-right for headline overlay. Editorial product photography. ${extra}`
    }
  ],
  "feature-1": [
    {
      id: "v1",
      text: (extra) => `Feature illustration for a SaaS landing page. Concept: ${BRAND.features[0].concept}. Bold flat design with clean strokes, consistent line weight, limited palette. Friendly geometric forms, intentional negative space. Landscape 4:3 composition. ${extra}`
    },
    {
      id: "v2",
      text: (extra) => `Editorial illustration for SaaS feature section. ${BRAND.features[0].concept}. Soft geometric shapes, warm muted gradients, subtle texture. Single clear focal point, professional but human-feeling. ${extra}`
    }
  ],
  "feature-2": [
    {
      id: "v1",
      text: (extra) => `Feature illustration for a SaaS landing page. Concept: ${BRAND.features[1].concept}. Bold flat design with clean strokes, consistent line weight, limited palette. Friendly geometric forms, intentional negative space. Landscape 4:3 composition. ${extra}`
    },
    {
      id: "v2",
      text: (extra) => `Editorial illustration for SaaS feature section. ${BRAND.features[1].concept}. Soft geometric shapes, warm muted gradients, subtle texture. Single clear focal point, professional but human-feeling. ${extra}`
    }
  ],
  "feature-3": [
    {
      id: "v1",
      text: (extra) => `Feature illustration for a SaaS landing page. Concept: ${BRAND.features[2].concept}. Bold flat design with clean strokes, consistent line weight, limited palette. Friendly geometric forms, intentional negative space. Landscape 4:3 composition. ${extra}`
    },
    {
      id: "v2",
      text: (extra) => `Editorial illustration for SaaS feature section. ${BRAND.features[2].concept}. Soft geometric shapes, warm muted gradients, subtle texture. Single clear focal point, professional but human-feeling. ${extra}`
    }
  ],
  "logo": [
    {
      id: "v1-inkwell-symbol",
      text: (extra) => `Geometric logo mark for "Inkwell", an AI email tool. Abstract symbol combining an inkwell vessel and a subtle spark/AI element. Symmetric composition, flat colors only, no gradients, no shadows, no texture. Strong silhouette, readable at 16px favicon size. 2-3 colors on transparent background.`
    },
    {
      id: "v2-letterform",
      text: (extra) => `Letterform logo mark using the letter "I" stylized as both an inkwell and a dripping ink drop. Geometric construction, single weight, asymmetric balance. Flat colors only, no gradients. Readable at 16px. Transparent background.`
    }
  ],
  "og": [
    {
      id: "v1-headline",
      text: (extra) => `Professional social media card design. Soft cream background #F5F0EB. Large bold "Write 10× faster, sound like you" in deep navy #2D4A7C, modern sans-serif, left-aligned. Below in smaller charcoal text: "Inkwell — AI email copilot". Subtle warm orange #E8A87C accent line on the right edge. Clean minimal layout. Landscape 16:9 composition. ${extra}`
    },
    {
      id: "v2-product-name",
      text: (extra) => `Social card for "Inkwell". Centered: large bold word "INKWELL" in deep navy #2D4A7C on cream #F5F0EB background. Below in lighter weight: "AI email copilot · Write in your voice". Small geometric inkwell icon on the right in warm orange #E8A87C. Editorial typography, generous margins. ${extra}`
    }
  ],
  "mockup": [
    {
      id: "v1-mac-mail",
      text: (extra) => `Clean macOS Mail app screenshot mockup. Inbox view on left with 5 sample email previews from common senders (e.g., "Sarah Chen — Re: Q2 planning"). Center: an open email thread. Right side panel labeled "Inkwell" showing an AI-drafted reply with a "Tone: Friendly" badge. Modern flat UI, deep navy #2D4A7C accents on cream #F5F0EB background. Sharp, photorealistic UI rendering. Transparent background outside the app window. ${extra}`
    },
    {
      id: "v2-floating-panel",
      text: (extra) => `Floating UI panel showing a single email composer with "Inkwell AI Assistant" branding. Three tone presets visible as pill buttons: "Formal", "Friendly", "Concise". A subtle glow under the active button (Friendly). Clean modern SaaS UI on transparent background, soft drop shadow under the panel. ${extra}`
    }
  ],
  "empty-state": [
    {
      id: "v1-inbox-zero",
      text: (extra) => `Friendly minimal illustration for an empty inbox state in an email web app. A small cheerful character holding an empty letter tray with a single sparkle, soft smile. Bold flat design, warm muted palette. Encouraging mood. Centered composition, square format. ${extra}`
    },
    {
      id: "v2-paper-airplane",
      text: (extra) => `Empty state illustration: a simple paper airplane mid-flight with motion lines, a tiny envelope icon as a star in the sky. Flat geometric design, warm muted gradients, encouraging and playful but professional. Centered, square format. ${extra}`
    }
  ]
};

// ---------- Models registry ----------
type ModelKey = "flux-2-pro" | "gpt-image-2" | "gpt-image-1.5" | "recraft-v4-pro" | "recraft-v4-vector" | "recraft-v3" | "ideogram-v3" | "ideogram-v3-transparent" | "nano-banana-pro";

interface ModelSpec {
  modelId: string;
  outExt: "webp" | "jpeg" | "png" | "svg";
  buildInput: (slot: Slot, prompt: string) => Record<string, unknown>;
  estimateCost: (slot: Slot) => number;
}

const RECRAFT_COLORS = [
  BRAND.colors.primary.rgb,
  BRAND.colors.accent.rgb,
  BRAND.colors.cream.rgb,
  BRAND.colors.charcoal.rgb
];

const MODELS: Record<ModelKey, ModelSpec> = {
  "flux-2-pro": {
    modelId: "fal-ai/flux-2-pro",
    outExt: "jpeg",
    buildInput: (slot, prompt) => ({
      prompt,
      image_size: SLOT_SIZES[slot],
      output_format: "jpeg",
      safety_tolerance: "2"
    }),
    estimateCost: () => 0.05
  },
  "gpt-image-2": {
    modelId: "fal-ai/gpt-image-2",
    outExt: "png",
    buildInput: (slot, prompt) => ({
      prompt,
      image_size: SLOT_SIZES[slot],
      quality: "high",
      output_format: "png",
      num_images: 1
    }),
    estimateCost: (slot) => {
      const { width, height } = SLOT_SIZES[slot];
      const px = width * height;
      if (px <= 1024 * 1024) return 0.22;
      if (px <= 2048 * 2048) return 0.30;
      return 0.41;
    }
  },
  "gpt-image-1.5": {
    modelId: "fal-ai/gpt-image-1.5",
    outExt: "png",
    buildInput: (slot, prompt) => {
      const { width, height } = SLOT_SIZES[slot];
      let imageSize = "1024x1024";
      if (slot === "mockup") imageSize = "1024x1024";
      else if (width > height) imageSize = "1536x1024";
      else if (height > width) imageSize = "1024x1536";
      return {
        prompt,
        image_size: imageSize,
        quality: "high",
        background: slot === "mockup" ? "transparent" : "opaque",
        output_format: "png"
      };
    },
    estimateCost: () => 0.20
  },
  "recraft-v4-pro": {
    modelId: "fal-ai/recraft/v4/pro/text-to-image",
    outExt: "webp",
    buildInput: (slot, prompt) => ({
      prompt,
      image_size: SLOT_SIZES[slot],
      colors: RECRAFT_COLORS
    }),
    estimateCost: () => 0.05
  },
  "recraft-v4-vector": {
    modelId: "fal-ai/recraft/v4/pro/text-to-vector",
    outExt: "svg",
    buildInput: (slot, prompt) => ({
      prompt,
      image_size: SLOT_SIZES[slot],
      colors: RECRAFT_COLORS,
      background_color: null
    }),
    estimateCost: () => 0.30
  },
  "recraft-v3": {
    modelId: "fal-ai/recraft/v3/text-to-image",
    outExt: "webp",
    buildInput: (slot, prompt) => ({
      prompt,
      image_size: SLOT_SIZES[slot]
    }),
    estimateCost: () => 0.04
  },
  "ideogram-v3": {
    modelId: "fal-ai/ideogram/v3",
    outExt: "png",
    buildInput: (slot, prompt) => {
      const isOg = slot === "og";
      const isFeatureOrEmpty = slot.startsWith("feature") || slot === "empty-state";
      return {
        prompt,
        image_size: SLOT_SIZES[slot],
        rendering_speed: "QUALITY",
        expand_prompt: false,
        style: isOg ? "DESIGN" : isFeatureOrEmpty ? "DESIGN" : "REALISTIC"
      };
    },
    estimateCost: () => 0.09
  },
  "ideogram-v3-transparent": {
    modelId: "fal-ai/ideogram/v3/generate-transparent",
    outExt: "png",
    buildInput: (slot, prompt) => ({
      prompt,
      image_size: SLOT_SIZES[slot],
      rendering_speed: "QUALITY",
      expand_prompt: false
    }),
    estimateCost: () => 0.09
  },
  "nano-banana-pro": {
    modelId: "fal-ai/nano-banana-pro",
    outExt: "png",
    buildInput: (slot, prompt) => {
      const { width, height } = SLOT_SIZES[slot];
      return {
        prompt,
        aspect_ratio: widthHeightToAspect(width, height),
        resolution: "2K",
        num_images: 1
      };
    },
    estimateCost: (slot) => {
      const { width, height } = SLOT_SIZES[slot];
      const px = width * height;
      return px > 2048 * 2048 ? 0.30 : 0.15;
    }
  }
};

// ---------- Slot × model matrix ----------
const SLOT_MODELS: Record<Slot, ModelKey[]> = {
  "hero":        ["flux-2-pro", "gpt-image-2", "nano-banana-pro", "ideogram-v3"],
  "feature-1":   ["recraft-v4-pro", "gpt-image-2", "nano-banana-pro", "ideogram-v3", "recraft-v3"],
  "feature-2":   ["recraft-v4-pro", "gpt-image-2", "nano-banana-pro", "ideogram-v3"],
  "feature-3":   ["recraft-v4-pro", "gpt-image-2", "nano-banana-pro", "ideogram-v3"],
  "logo":        ["recraft-v4-vector", "recraft-v3"],
  "og":          ["ideogram-v3", "gpt-image-2", "nano-banana-pro"],
  "mockup":      ["gpt-image-1.5", "gpt-image-2", "ideogram-v3-transparent", "flux-2-pro"],
  "empty-state": ["recraft-v4-pro", "gpt-image-2", "nano-banana-pro", "ideogram-v3"]
};

// ---------- Build run plan ----------
interface RunRow {
  id: string;
  slot: Slot;
  modelKey: ModelKey;
  modelId: string;
  variantId: string;
  prompt: string;
  outPath: string;
  estCost: number;
}
function buildPlan(): RunRow[] {
  const rows: RunRow[] = [];
  for (const slot of Object.keys(SLOT_MODELS) as Slot[]) {
    const models = SLOT_MODELS[slot];
    const variants = PROMPTS[slot];
    for (const modelKey of models) {
      const spec = MODELS[modelKey];
      for (const v of variants) {
        const prompt = v.text(BRAND.visualPrefix);
        const id = `${slot}-${modelKey}-${v.id}`;
        const outPath = join(IMAGES_DIR, slot, modelKey, `${v.id}.${spec.outExt}`);
        rows.push({
          id,
          slot,
          modelKey,
          modelId: spec.modelId,
          variantId: v.id,
          prompt,
          outPath,
          estCost: spec.estimateCost(slot)
        });
      }
    }
  }
  return rows;
}

// ---------- Execution ----------
async function ensureDir(d: string) {
  if (!existsSync(d)) await mkdir(d, { recursive: true });
}

async function downloadFile(url: string, path: string) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status} downloading ${url}`);
  const buf = Buffer.from(await r.arrayBuffer());
  await writeFile(path, buf);
}

interface RunResult extends RunRow {
  status: "success" | "failed";
  error: string | null;
  latencyMs: number;
  imageUrl: string | null;
  hasWatermark?: boolean;
}

async function runOne(row: RunRow): Promise<RunResult> {
  const spec = MODELS[row.modelKey];
  const input = spec.buildInput(row.slot, row.prompt);
  const start = Date.now();
  try {
    const result: any = await fal.subscribe(row.modelId, { input });
    const latencyMs = Date.now() - start;
    const data = result.data || result;
    const imageUrl: string | undefined =
      data?.images?.[0]?.url ||
      data?.image?.url ||
      (typeof data?.image === "string" ? data.image : undefined);
    if (!imageUrl) throw new Error(`No image URL in response: ${JSON.stringify(data).slice(0, 300)}`);
    await ensureDir(join(IMAGES_DIR, row.slot, row.modelKey));
    await downloadFile(imageUrl, row.outPath);
    return { ...row, status: "success", error: null, latencyMs, imageUrl };
  } catch (e: any) {
    const latencyMs = Date.now() - start;
    return { ...row, status: "failed", error: String(e?.message || e), latencyMs, imageUrl: null };
  }
}

async function runWithConcurrency<T, R>(items: T[], n: number, fn: (item: T, i: number) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let idx = 0;
  const workers = Array.from({ length: Math.min(n, items.length) }, async () => {
    while (true) {
      const i = idx++;
      if (i >= items.length) return;
      out[i] = await fn(items[i], i);
    }
  });
  await Promise.all(workers);
  return out;
}

async function main() {
  const startedAt = new Date().toISOString();
  await ensureDir(OUTPUT_ROOT);
  await ensureDir(IMAGES_DIR);
  const plan = buildPlan();
  console.log(`[bakeoff] plan: ${plan.length} generations across ${Object.keys(SLOT_SIZES).length} slots`);
  const totalEst = plan.reduce((s, r) => s + r.estCost, 0);
  console.log(`[bakeoff] estimated cost: $${totalEst.toFixed(2)}`);

  await writeFile(join(OUTPUT_ROOT, "prompts.json"), JSON.stringify({ scenario: BRAND, plan: plan.map(r => ({ id: r.id, slot: r.slot, modelKey: r.modelKey, variantId: r.variantId, prompt: r.prompt })) }, null, 2));

  const results = await runWithConcurrency(plan, 4, async (row, i) => {
    process.stdout.write(`[${i + 1}/${plan.length}] ${row.id} ... `);
    const r = await runOne(row);
    process.stdout.write(`${r.status} (${r.latencyMs}ms${r.error ? ", " + r.error.slice(0, 80) : ""})\n`);
    return r;
  });

  const endedAt = new Date().toISOString();
  const summary = {
    scenario: BRAND,
    started_at: startedAt,
    ended_at: endedAt,
    total_planned: plan.length,
    successes: results.filter(r => r.status === "success").length,
    failures: results.filter(r => r.status === "failed").length,
    estimated_cost_usd_total: Number(results.reduce((s, r) => s + (r.status === "success" ? r.estCost : 0), 0).toFixed(2)),
    candidates: results.map(r => ({
      id: r.id,
      slot: r.slot,
      model_key: r.modelKey,
      model_id: r.modelId,
      variant: r.variantId,
      status: r.status,
      error: r.error,
      latency_ms: r.latencyMs,
      output_path: r.status === "success" ? r.outPath.replace(REPO_ROOT + "/", "") : null,
      estimated_cost_usd: r.status === "success" ? r.estCost : 0
    }))
  };
  await writeFile(join(OUTPUT_ROOT, "candidates.json"), JSON.stringify(summary, null, 2));
  console.log(`[bakeoff] done. ${summary.successes}/${summary.total_planned} succeeded. cost ~$${summary.estimated_cost_usd_total}.`);
  console.log(`[bakeoff] output: ${OUTPUT_ROOT}`);
  if (summary.failures > 0) {
    console.log(`[bakeoff] failures:`);
    for (const c of summary.candidates) {
      if (c.status === "failed") console.log(`  - ${c.id}: ${c.error?.slice(0, 200)}`);
    }
  }
}

main().catch(e => { console.error(e); process.exit(1); });
