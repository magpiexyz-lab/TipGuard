// AI: Anthropic (Claude SDK). Scoped to PROSE ONLY per experiment.yaml
// `stack.ai: anthropic` — plain-English violation explanations and notice
// wording polish. Rule resolution (state-rules.ts), score computation
// (scoring.ts), and violation detection (violation-rules.ts) are deterministic
// pure functions and MUST NEVER call into this module or depend on model
// output. No caller in this codebase may present AI-polished prose as
// attorney-certified language — the counsel-review disclaimer in
// notice-generator.ts covers every generated notice regardless of whether AI
// prose polish was applied.

import Anthropic from "@anthropic-ai/sdk";

const DEFAULT_MODEL = "claude-opus-4-6";
const MAX_RETRIES = 3;
const BASE_DELAY_MS = 1000;

let _client: Anthropic | null = null;

function createDemoClient() {
  return {
    messages: {
      create: async (params: { stream?: boolean }) => {
        if (params.stream) {
          return {
            async *[Symbol.asyncIterator]() {
              yield {
                type: "content_block_delta" as const,
                delta: { type: "text_delta" as const, text: "[demo response]" },
              };
              yield {
                type: "message_stop" as const,
              };
            },
          };
        }
        return {
          id: "demo",
          content: [{ type: "text" as const, text: "[demo response]" }],
          model: DEFAULT_MODEL,
          role: "assistant" as const,
          stop_reason: "end_turn" as const,
          usage: { input_tokens: 0, output_tokens: 0 },
        };
      },
    },
  } as unknown as Anthropic;
}

function getClient(): Anthropic {
  if (process.env.DEMO_MODE === "true" && process.env.VERCEL === "1") {
    throw new Error("DEMO_MODE is not allowed in production");
  }
  if (process.env.DEMO_MODE === "true") return createDemoClient();
  if (!_client) {
    if (!process.env.ANTHROPIC_API_KEY) {
      throw new Error("ANTHROPIC_API_KEY is not configured");
    }
    _client = new Anthropic(); // reads ANTHROPIC_API_KEY from env automatically
  }
  return _client;
}

function isRetryable(error: unknown): boolean {
  if (error instanceof Anthropic.RateLimitError) return true;
  if (error instanceof Anthropic.InternalServerError) return true;
  if (error instanceof Anthropic.APIConnectionError) return true;
  return false;
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// --- Public API ---

export type MessageParams = Omit<
  Anthropic.MessageCreateParamsNonStreaming,
  "model"
> & {
  model?: string;
};

export type StreamParams = Omit<
  Anthropic.MessageCreateParamsStreaming,
  "model" | "stream"
> & {
  model?: string;
};

/**
 * Send a message to Claude. Retries on transient errors with exponential backoff.
 */
export async function ask(params: MessageParams): Promise<Anthropic.Message> {
  const { model = DEFAULT_MODEL, ...rest } = params;
  let lastError: unknown;

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      return await getClient().messages.create({
        model,
        ...rest,
        stream: false,
      });
    } catch (error) {
      lastError = error;
      if (!isRetryable(error) || attempt === MAX_RETRIES - 1) throw error;
      await sleep(BASE_DELAY_MS * Math.pow(2, attempt));
    }
  }

  throw lastError;
}

/**
 * Stream a message from Claude. Retries on transient errors before first chunk.
 * Returns an async iterable of streaming events.
 */
export async function stream(
  params: StreamParams
) {
  const { model = DEFAULT_MODEL, ...rest } = params;
  let lastError: unknown;

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      return getClient().messages.stream({
        model,
        ...rest,
      });
    } catch (error) {
      lastError = error;
      if (!isRetryable(error) || attempt === MAX_RETRIES - 1) throw error;
      await sleep(BASE_DELAY_MS * Math.pow(2, attempt));
    }
  }

  throw lastError;
}

/**
 * Extract the text content from a Claude response.
 */
export function getText(message: Anthropic.Message): string {
  return message.content
    .filter((block): block is Anthropic.TextBlock => block.type === "text")
    .map((block) => block.text)
    .join("");
}
