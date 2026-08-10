import { fal } from "@fal-ai/client";
import { writeFile, mkdir, unlink } from "fs/promises";
import { existsSync, readFileSync } from "fs";
import { join, extname } from "path";
import { homedir } from "os";
import { createHash } from "crypto";
import sharp from "sharp";

const MAX_RETRIES = 2;
const BASE_DELAY_MS = 2000;
const PUBLIC_IMAGES_DIR = join(process.cwd(), "public", "images");
const ERROR_LOG = join(process.cwd(), ".runs", "fal-api-errors.jsonl");

/** Dimension Contract: longest side of every written raster must be <= 1920px. */
const MAX_EDGE = 1920;

const FALLBACK_MODEL = "fal-ai/flux-2-pro";

// --- Model Configuration ---

export type ImageType =
  | "hero"
  | "feature"
  | "logo"
  | "og"
  | "mockup"
  | "empty-state";

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
  /** For Recraft models — brand color control. */
  colors?: Array<{ r: number; g: number; b: number }>;
  /** For Recraft vector — pass null for a transparent field. */
  backgroundColor?: { r: number; g: number; b: number } | null;
  /** Override output directory (default: public/images). */
  outputDir?: string;
  /** Explicit model override (bypasses MODEL_CONFIGS[type].modelId). */
  modelOverride?: string;
  /** Write a sibling <file>.provenance.json (#1272). Default: true. */
  writeProvenance?: boolean;
}

export interface ImageResult {
  path: string;
  publicPath: string;
  altText: string;
  fallback: boolean;
  model: string;
  seed: number | null;
  promptHash: string;
  width?: number;
  height?: number;
}

// --- Internal ---

function isDemoMode(): boolean {
  if (process.env.DEMO_MODE === "true") return true;
  if (process.env.FAL_KEY) return false;
  try {
    const keyPath = join(homedir(), ".fal", "key");
    const key = readFileSync(keyPath, "utf-8").trim();
    if (key && !key.startsWith("placeholder")) {
      process.env.FAL_KEY = key; // Bridge to env var for the fal client
      return false;
    }
  } catch {
    /* ~/.fal/key not readable */
  }
  return !process.env.FAL_KEY;
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function ensureDir(dir: string = PUBLIC_IMAGES_DIR): Promise<void> {
  if (!existsSync(dir)) {
    await mkdir(dir, { recursive: true });
  }
}

function hashPrompt(prompt: string): string {
  return createHash("sha256").update(prompt).digest("hex").slice(0, 16);
}

/** #1261: external-actor witness for every non-2xx fal response. */
async function logFalError(entry: {
  slot: string;
  model: string;
  http_status: number | string;
  error_body: string;
}): Promise<void> {
  try {
    await ensureDir(join(process.cwd(), ".runs"));
    const line =
      JSON.stringify({
        ...entry,
        error_body: String(entry.error_body).slice(0, 500),
        attempted_at: new Date().toISOString(),
      }) + "\n";
    const { appendFile } = await import("fs/promises");
    await appendFile(ERROR_LOG, line, "utf-8");
  } catch {
    /* logging must never break generation */
  }
}

interface ModelCall {
  url: string;
  seed: number | null;
  contentType?: string;
}

async function callModel(
  modelId: string,
  input: Record<string, unknown>
): Promise<ModelCall> {
  const result = await fal.subscribe(modelId, { input });
  const data = result.data as {
    images?: { url: string; content_type?: string }[];
    image?: { url: string; content_type?: string };
    seed?: number;
  };
  const img = data.images?.[0] ?? data.image;
  const url = img?.url;
  if (!url) throw new Error(`No image URL from ${modelId}`);
  return {
    url,
    seed: typeof data.seed === "number" ? data.seed : null,
    contentType: img?.content_type,
  };
}

async function fetchBuffer(url: string): Promise<Buffer> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Download failed: ${response.status}`);
  return Buffer.from(await response.arrayBuffer());
}

/**
 * Dimension Contract enforcement. Rasters are resized to fit inside
 * MAX_EDGE x MAX_EDGE (never upscaled) and encoded to match the target
 * file extension. SVG passes through untouched.
 */
export async function writeCapped(
  buffer: Buffer,
  filePath: string
): Promise<{ width?: number; height?: number }> {
  const ext = extname(filePath).toLowerCase();

  if (ext === ".svg") {
    await writeFile(filePath, buffer);
    return {};
  }

  let pipeline = sharp(buffer).resize({
    width: MAX_EDGE,
    height: MAX_EDGE,
    fit: "inside",
    withoutEnlargement: true,
  });

  if (ext === ".webp") pipeline = pipeline.webp({ quality: 90 });
  else if (ext === ".png") pipeline = pipeline.png({ compressionLevel: 9 });
  else if (ext === ".jpg" || ext === ".jpeg")
    pipeline = pipeline.jpeg({ quality: 88 });

  const info = await pipeline.toFile(filePath);
  return { width: info.width, height: info.height };
}

async function writeProvenanceFile(
  filePath: string,
  provenance: Record<string, unknown>
): Promise<void> {
  await writeFile(
    `${filePath}.provenance.json`,
    JSON.stringify(provenance, null, 2),
    "utf-8"
  );
}

// --- Public API ---

/**
 * Generate an image using the optimal model for the image type.
 * Falls back to FLUX.2 Pro if the specialized model fails,
 * then to an SVG placeholder if all API calls fail.
 */
export async function generateImage(
  options: GenerateImageOptions
): Promise<ImageResult> {
  const {
    type,
    prompt,
    width,
    height,
    filename,
    altText,
    colors,
    backgroundColor,
    outputDir,
    modelOverride,
    writeProvenance = true,
  } = options;

  const config = MODEL_CONFIGS[type];
  const primaryModel = modelOverride ?? config.modelId;
  const targetDir = outputDir ?? PUBLIC_IMAGES_DIR;
  const filePath = join(targetDir, filename);
  const publicPath = outputDir ? `${outputDir}/${filename}` : `/images/${filename}`;
  const promptHash = hashPrompt(prompt);

  await ensureDir(targetDir);

  if (isDemoMode()) {
    return generateSvgPlaceholder({ width, height, filename, altText, outputDir });
  }

  const input: Record<string, unknown> = { prompt, ...config.defaultParams };

  // Align to 16-pixel multiples (required by GPT-Image-2; harmless elsewhere).
  const alignedW = Math.round(width / 16) * 16;
  const alignedH = Math.round(height / 16) * 16;
  input.image_size = { width: alignedW, height: alignedH };

  if (colors && primaryModel.includes("recraft")) {
    input.colors = colors;
  }
  if (backgroundColor !== undefined && primaryModel.includes("recraft")) {
    input.background_color = backgroundColor;
  }

  const modelsToTry =
    primaryModel === FALLBACK_MODEL ? [primaryModel] : [primaryModel, FALLBACK_MODEL];

  for (const modelId of modelsToTry) {
    const modelInput =
      modelId === FALLBACK_MODEL && modelId !== primaryModel
        ? {
            prompt,
            image_size: { width: alignedW, height: alignedH },
            output_format: "jpeg",
            safety_tolerance: "2",
          }
        : input;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        const call = await callModel(modelId, modelInput);
        const buffer = await fetchBuffer(call.url);
        const dims = await writeCapped(buffer, filePath);

        if (writeProvenance) {
          await writeProvenanceFile(filePath, {
            model: modelId,
            prompt,
            prompt_hash: promptHash,
            seed: call.seed,
            width: dims.width ?? null,
            height: dims.height ?? null,
            generated_at: new Date().toISOString(),
          });
        }

        return {
          path: filePath,
          publicPath,
          altText,
          fallback: false,
          model: modelId,
          seed: call.seed,
          promptHash,
          ...dims,
        };
      } catch (error) {
        const err = error as { status?: number; body?: unknown; message?: string };
        await logFalError({
          slot: filename,
          model: modelId,
          http_status: err.status ?? "unknown",
          error_body:
            typeof err.body === "string"
              ? err.body
              : JSON.stringify(err.body ?? err.message ?? String(error)),
        });

        if (attempt < MAX_RETRIES) {
          await sleep(BASE_DELAY_MS * Math.pow(2, attempt));
        } else if (modelId !== FALLBACK_MODEL) {
          console.warn(`${modelId} failed for ${filename}, trying fallback...`);
          break;
        }
      }
    }
  }

  console.warn(`All models failed for ${filename}, using SVG placeholder`);
  return generateSvgPlaceholder({ width, height, filename, altText, outputDir });
}

/**
 * Download a photo from a URL (e.g. Unsplash CDN) through the same
 * dimension-cap + provenance path used for AI candidates.
 */
export async function fetchPhotoCandidate(options: {
  url: string;
  filename: string;
  altText: string;
  outputDir?: string;
  source: string;
  sourceId: string;
  searchQuery: string;
}): Promise<ImageResult> {
  const { url, filename, altText, outputDir, source, sourceId, searchQuery } = options;
  const targetDir = outputDir ?? PUBLIC_IMAGES_DIR;
  const filePath = join(targetDir, filename);
  await ensureDir(targetDir);

  const buffer = await fetchBuffer(url);
  const dims = await writeCapped(buffer, filePath);

  await writeProvenanceFile(filePath, {
    model: source,
    prompt: searchQuery,
    prompt_hash: hashPrompt(`${source}:${sourceId}:${searchQuery}`),
    seed: null,
    source_id: sourceId,
    source_url: url,
    width: dims.width ?? null,
    height: dims.height ?? null,
    generated_at: new Date().toISOString(),
  });

  return {
    path: filePath,
    publicPath: outputDir ? `${outputDir}/${filename}` : `/images/${filename}`,
    altText,
    fallback: false,
    model: source,
    seed: null,
    promptHash: hashPrompt(`${source}:${sourceId}:${searchQuery}`),
    ...dims,
  };
}

/** Copy a candidate to its canonical public path, re-applying the cap. */
export async function promoteCandidate(
  candidatePath: string,
  canonicalFilename: string
): Promise<string> {
  await ensureDir(PUBLIC_IMAGES_DIR);
  const target = join(PUBLIC_IMAGES_DIR, canonicalFilename);
  const buffer = readFileSync(candidatePath);
  if (existsSync(target)) await unlink(target);
  await writeCapped(buffer, target);
  return target;
}

/**
 * Generate a themed SVG placeholder at the same file path.
 */
export async function generateSvgPlaceholder(options: {
  width: number;
  height: number;
  filename: string;
  altText: string;
  outputDir?: string;
}): Promise<ImageResult> {
  const { width, height, filename, altText, outputDir } = options;
  const svgFilename = filename.replace(/\.\w+$/, ".svg");
  const targetDir = outputDir ?? PUBLIC_IMAGES_DIR;
  const filePath = join(targetDir, svgFilename);
  const publicPath = outputDir
    ? `${outputDir}/${svgFilename}`
    : `/images/${svgFilename}`;

  await ensureDir(targetDir);

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">
  <rect width="${width}" height="${height}" fill="#F3F0E6"/>
  <rect x="0" y="0" width="${width}" height="${height}" fill="none" stroke="#171C13" stroke-opacity="0.08"/>
  <circle cx="${width * 0.5}" cy="${height * 0.5}" r="${Math.min(width, height) * 0.18}" fill="#C89230" fill-opacity="0.12"/>
</svg>`;

  await writeFile(filePath, svg, "utf-8");
  return {
    path: filePath,
    publicPath,
    altText,
    fallback: true,
    model: "svg-placeholder",
    seed: null,
    promptHash: hashPrompt(altText),
  };
}
