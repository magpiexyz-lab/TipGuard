// In-memory fixed-window rate limiter (Rule 6). Guards auth, POST
// /api/checkout, and the fully public POST /api/notices/sign.
//
// TODO: Upgrade to Upstash Redis for cross-instance limiting. Until then the
// store is per-instance, which is why it must be self-trimming (see below).

const rateLimitMap = new Map<string, { count: number; resetTime: number }>();

// The store is unbounded by construction: every distinct key creates an entry
// and nothing in the request path removes it. On the public /api/notices/sign
// endpoint a caller that can vary the rate-limit key mints a fresh entry per
// request, so an unswept map is a memory-exhaustion vector in the very module
// whose job is to stop abuse. Sweep expired entries, but only when the store
// is actually large AND at most once per interval — an unconditional O(n) scan
// per insert would turn a key flood into quadratic work, which is worse than
// the leak it fixes.
const SWEEP_THRESHOLD = 512;
const SWEEP_INTERVAL_MS = 60_000;
let nextSweepAt = 0;

function sweepExpired(now: number): void {
  if (rateLimitMap.size < SWEEP_THRESHOLD || now < nextSweepAt) return;
  nextSweepAt = now + SWEEP_INTERVAL_MS;
  for (const [key, entry] of rateLimitMap) {
    if (now > entry.resetTime) rateLimitMap.delete(key);
  }
}

/** Number of tracked keys. Exposed for leak tests and ops introspection. */
export function rateLimitStoreSize(): number {
  return rateLimitMap.size;
}

export function rateLimit(
  key: string,
  { limit = 10, windowMs = 60_000 }: { limit?: number; windowMs?: number } = {}
): { success: boolean; remaining: number } {
  // A limiter configured to allow nothing must allow nothing. Falling through
  // would return { success: true, remaining: -1 } and open a closed endpoint.
  if (limit <= 0) return { success: false, remaining: 0 };

  const now = Date.now();
  const entry = rateLimitMap.get(key);

  if (!entry || now > entry.resetTime) {
    sweepExpired(now);
    rateLimitMap.set(key, { count: 1, resetTime: now + windowMs });
    return { success: true, remaining: limit - 1 };
  }

  if (entry.count >= limit) {
    return { success: false, remaining: 0 };
  }

  entry.count++;
  return { success: true, remaining: limit - entry.count };
}

// Vercel's proxy appends the verified client IP as the LAST entry in the
// X-Forwarded-For chain. Entries BEFORE the last one are forwarded from the
// client (or upstream proxies) and are NOT trusted — an attacker can supply
// arbitrary `X-Forwarded-For: <random>` to inject a unique-per-request key,
// bypassing per-IP rate caps. Always derive the rate-limit key via this
// helper, never via the raw header value.
export function clientIpFromHeaders(headers: Headers): string {
  const xff = headers.get("x-forwarded-for");
  if (xff) {
    const last = xff.split(",").at(-1)?.trim();
    if (last) return last;
  }
  return headers.get("x-real-ip") ?? "unknown";
}
