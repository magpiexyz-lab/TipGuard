import { fal } from "@fal-ai/client";
import { readFileSync } from "fs";
import { join } from "path";
import { homedir } from "os";

const key = process.env.FAL_KEY || readFileSync(join(homedir(), ".fal", "key"), "utf-8").trim();
fal.config({ credentials: key });

async function pingOne(modelId: string, input: Record<string, unknown>) {
  const t = Date.now();
  try {
    const r: any = await fal.subscribe(modelId, { input });
    const url = r.data?.images?.[0]?.url || r.data?.image?.url;
    console.log(`[OK] ${modelId} (${Date.now() - t}ms) -> ${url?.slice(0, 80)}...`);
    return { ok: true, url };
  } catch (e: any) {
    console.log(`[ERR] ${modelId} (${Date.now() - t}ms) -> ${String(e?.message || e).slice(0, 200)}`);
    return { ok: false, err: e };
  }
}

async function main() {
  console.log("--- pinging key endpoints ---");
  await pingOne("fal-ai/flux-2-pro", { prompt: "a red apple", image_size: { width: 512, height: 512 }, output_format: "jpeg" });
  await pingOne("fal-ai/gpt-image-2", { prompt: "a red apple", image_size: { width: 1024, height: 1024 }, quality: "low", output_format: "png" });
  await pingOne("fal-ai/nano-banana-pro", { prompt: "a red apple", aspect_ratio: "1:1", resolution: "2K" });
  await pingOne("fal-ai/ideogram/v3", { prompt: "a red apple", image_size: { width: 1024, height: 1024 }, rendering_speed: "TURBO" });
  await pingOne("fal-ai/ideogram/v3/generate-transparent", { prompt: "a red apple", image_size: { width: 512, height: 512 }, rendering_speed: "TURBO" });
  await pingOne("fal-ai/recraft/v4/pro/text-to-image", { prompt: "a red apple", image_size: { width: 512, height: 512 } });
  await pingOne("fal-ai/recraft/v4/pro/text-to-vector", { prompt: "a red apple icon, flat colors", image_size: { width: 512, height: 512 } });
  await pingOne("fal-ai/recraft/v3/text-to-image", { prompt: "a red apple", image_size: { width: 512, height: 512 } });
  await pingOne("fal-ai/gpt-image-1.5", { prompt: "a red apple", image_size: "1024x1024", quality: "low", output_format: "png" });
}

main().catch(e => { console.error(e); process.exit(1); });
