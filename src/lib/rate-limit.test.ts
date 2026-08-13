// Unit tests for the Rule 6 rate-limit control.
//
// This module guards signup/login (auth), POST /api/checkout (payment), and
// POST /api/notices/sign — the last of which is fully public: an anonymous
// caller with a signing link is the only actor, so this limiter is the ONLY
// thing between the internet and the signature vault. Call sites use
// `rateLimit(\`<scope>:${clientIpFromHeaders(req.headers)}\`, {...})` and return
// 429 when `success` is false.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clientIpFromHeaders,
  rateLimit,
  rateLimitStoreSize,
} from "./rate-limit";

/** Unique key per test — the store is module-level and shared across tests. */
let keySeq = 0;
function uniqueKey(scope = "test"): string {
  keySeq += 1;
  return `${scope}:${keySeq}:${Math.random().toString(36).slice(2)}`;
}

describe("rateLimit — allowance within a window", () => {
  it("allows the first request and reports one fewer than the limit remaining", () => {
    const result = rateLimit(uniqueKey(), { limit: 5, windowMs: 60_000 });
    expect(result.success).toBe(true);
    expect(result.remaining).toBe(4);
  });

  it("allows exactly `limit` requests in a window and denies the next", () => {
    const key = uniqueKey("checkout");
    for (let i = 1; i <= 10; i++) {
      expect(rateLimit(key, { limit: 10, windowMs: 60_000 }).success).toBe(true);
    }
    expect(rateLimit(key, { limit: 10, windowMs: 60_000 })).toEqual({
      success: false,
      remaining: 0,
    });
  });

  it("decrements remaining by exactly one per allowed request, ending at 0", () => {
    const key = uniqueKey();
    const seen = [];
    for (let i = 0; i < 4; i++) {
      seen.push(rateLimit(key, { limit: 4, windowMs: 60_000 }).remaining);
    }
    expect(seen).toEqual([3, 2, 1, 0]);
  });

  it("keeps denying once the budget is spent (a denial does not restore budget)", () => {
    const key = uniqueKey("notices-sign");
    for (let i = 0; i < 3; i++) rateLimit(key, { limit: 3, windowMs: 60_000 });
    for (let i = 0; i < 20; i++) {
      expect(rateLimit(key, { limit: 3, windowMs: 60_000 })).toEqual({
        success: false,
        remaining: 0,
      });
    }
  });

  it("never reports a negative remaining, on any path", () => {
    const key = uniqueKey();
    for (let i = 0; i < 30; i++) {
      expect(rateLimit(key, { limit: 5, windowMs: 60_000 }).remaining).toBeGreaterThanOrEqual(0);
    }
  });

  it("defaults to 10 requests per 60 seconds when no options are supplied", () => {
    const key = uniqueKey();
    expect(rateLimit(key).remaining).toBe(9);
    for (let i = 0; i < 9; i++) rateLimit(key);
    expect(rateLimit(key).success).toBe(false);
  });

  it("denies every request when the limit is zero", () => {
    // A limiter configured to allow nothing must allow nothing. Returning
    // success:true with remaining:-1 would silently open a closed endpoint.
    const key = uniqueKey();
    expect(rateLimit(key, { limit: 0, windowMs: 60_000 })).toEqual({
      success: false,
      remaining: 0,
    });
    expect(rateLimit(key, { limit: 0, windowMs: 60_000 }).success).toBe(false);
  });

  it("denies every request when the limit is negative", () => {
    expect(rateLimit(uniqueKey(), { limit: -1, windowMs: 60_000 })).toEqual({
      success: false,
      remaining: 0,
    });
  });
});

describe("rateLimit — key isolation", () => {
  it("gives each key an independent budget", () => {
    const a = uniqueKey("checkout");
    const b = uniqueKey("checkout");
    for (let i = 0; i < 3; i++) rateLimit(a, { limit: 3, windowMs: 60_000 });
    expect(rateLimit(a, { limit: 3, windowMs: 60_000 }).success).toBe(false);
    expect(rateLimit(b, { limit: 3, windowMs: 60_000 }).success).toBe(true);
  });

  it("does not let one route's traffic consume another route's budget for the same IP", () => {
    // Call sites namespace by scope: `checkout:1.2.3.4` vs `feedback:1.2.3.4`.
    const ip = uniqueKey("ip");
    const checkoutKey = `checkout:${ip}`;
    const feedbackKey = `feedback:${ip}`;
    for (let i = 0; i < 5; i++) rateLimit(feedbackKey, { limit: 5, windowMs: 60_000 });
    expect(rateLimit(feedbackKey, { limit: 5, windowMs: 60_000 }).success).toBe(false);
    expect(rateLimit(checkoutKey, { limit: 10, windowMs: 60_000 }).success).toBe(true);
  });
});

describe("rateLimit — window behaviour", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not reset the counter before the window elapses", () => {
    const key = uniqueKey();
    for (let i = 0; i < 3; i++) rateLimit(key, { limit: 3, windowMs: 60_000 });
    vi.advanceTimersByTime(59_999);
    expect(rateLimit(key, { limit: 3, windowMs: 60_000 }).success).toBe(false);
  });

  it("resets the counter once the window has elapsed", () => {
    const key = uniqueKey();
    for (let i = 0; i < 3; i++) rateLimit(key, { limit: 3, windowMs: 60_000 });
    expect(rateLimit(key, { limit: 3, windowMs: 60_000 }).success).toBe(false);

    vi.advanceTimersByTime(60_001);

    const afterReset = rateLimit(key, { limit: 3, windowMs: 60_000 });
    expect(afterReset.success).toBe(true);
    expect(afterReset.remaining).toBe(2);
  });

  it("uses a fixed window anchored at the first request, not a sliding one", () => {
    // A sliding window would push resetTime out on every request, so a caller
    // making one request every 30s would never reset — and, worse, a caller
    // spending its budget would stay locked out indefinitely.
    const key = uniqueKey();
    rateLimit(key, { limit: 3, windowMs: 60_000 });
    vi.advanceTimersByTime(30_000);
    rateLimit(key, { limit: 3, windowMs: 60_000 });
    vi.advanceTimersByTime(30_001); // 60_001ms after the FIRST request
    const afterReset = rateLimit(key, { limit: 3, windowMs: 60_000 });
    expect(afterReset.success).toBe(true);
    expect(afterReset.remaining).toBe(2);
  });

  it("honours a custom window length", () => {
    const key = uniqueKey();
    rateLimit(key, { limit: 1, windowMs: 1_000 });
    expect(rateLimit(key, { limit: 1, windowMs: 1_000 }).success).toBe(false);
    vi.advanceTimersByTime(1_001);
    expect(rateLimit(key, { limit: 1, windowMs: 1_000 }).success).toBe(true);
  });
});

describe("rateLimit — store growth", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-02-01T00:00:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("evicts expired entries so the store does not grow without bound", () => {
    // POST /api/notices/sign is public and unauthenticated. On a non-Vercel or
    // misconfigured deployment an attacker controls the X-Forwarded-For chain
    // and can mint a fresh key per request. Without eviction, every key it has
    // ever seen is retained for the lifetime of the process — a memory
    // exhaustion vector in the module whose whole job is to stop abuse.
    for (let i = 0; i < 1_000; i++) {
      rateLimit(`sign:flood-${i}`, { limit: 10, windowMs: 60_000 });
    }
    // All 1,000 flood keys are inside their window, so all are still tracked.
    expect(rateLimitStoreSize()).toBeGreaterThanOrEqual(1_000);

    vi.advanceTimersByTime(60_001);
    rateLimit("sign:live", { limit: 10, windowMs: 60_000 });

    // Every flood key has now expired and must be gone.
    expect(rateLimitStoreSize()).toBeLessThan(1_000);
  });

  it("does not evict entries that are still inside their window", () => {
    const key = uniqueKey("still-live");
    rateLimit(key, { limit: 3, windowMs: 600_000 });
    vi.advanceTimersByTime(1_000);
    for (let i = 0; i < 200; i++) {
      rateLimit(`churn-${i}`, { limit: 10, windowMs: 1 });
    }
    vi.advanceTimersByTime(1_000);
    rateLimit(uniqueKey("sweep-trigger"), { limit: 10, windowMs: 60_000 });

    // The long-window key must still be counting, not silently reset.
    expect(rateLimit(key, { limit: 3, windowMs: 600_000 }).remaining).toBe(1);
  });
});

describe("clientIpFromHeaders", () => {
  it("returns the LAST x-forwarded-for entry — the platform-verified client IP", () => {
    const headers = new Headers({ "x-forwarded-for": "10.0.0.1, 203.0.113.7" });
    expect(clientIpFromHeaders(headers)).toBe("203.0.113.7");
  });

  it("ignores client-supplied entries earlier in the chain (spoof resistance)", () => {
    // Two requests from the same real IP that prepend different junk must land
    // in the SAME bucket. If they did not, prepending a random value would
    // bypass every per-IP cap in the app.
    const spoofA = new Headers({ "x-forwarded-for": "1.1.1.1, 203.0.113.7" });
    const spoofB = new Headers({ "x-forwarded-for": "2.2.2.2, 203.0.113.7" });
    const spoofC = new Headers({
      "x-forwarded-for": "evil, 9.9.9.9, 8.8.8.8, 203.0.113.7",
    });
    expect(clientIpFromHeaders(spoofA)).toBe(clientIpFromHeaders(spoofB));
    expect(clientIpFromHeaders(spoofC)).toBe("203.0.113.7");
  });

  it("shares one rate-limit bucket across spoofed prefixes from the same client", () => {
    const realIp = `203.0.113.${(keySeq += 1) % 250}`;
    const scope = uniqueKey("spoof-scope");
    const keyFor = (prefix: string) =>
      `${scope}:${clientIpFromHeaders(
        new Headers({ "x-forwarded-for": `${prefix}, ${realIp}` })
      )}`;
    for (let i = 0; i < 3; i++) {
      expect(rateLimit(keyFor(`attacker-${i}`), { limit: 3, windowMs: 60_000 }).success).toBe(true);
    }
    expect(rateLimit(keyFor("attacker-fresh"), { limit: 3, windowMs: 60_000 }).success).toBe(false);
  });

  it("trims surrounding whitespace from the extracted entry", () => {
    const headers = new Headers({ "x-forwarded-for": "10.0.0.1,   203.0.113.7   " });
    expect(clientIpFromHeaders(headers)).toBe("203.0.113.7");
  });

  it("returns the sole entry when the chain has only one hop", () => {
    expect(
      clientIpFromHeaders(new Headers({ "x-forwarded-for": "203.0.113.7" }))
    ).toBe("203.0.113.7");
  });

  it("handles an IPv6 client address", () => {
    const headers = new Headers({
      "x-forwarded-for": "10.0.0.1, 2001:db8::8a2e:370:7334",
    });
    expect(clientIpFromHeaders(headers)).toBe("2001:db8::8a2e:370:7334");
  });

  it("is case-insensitive about the header name", () => {
    expect(
      clientIpFromHeaders(new Headers({ "X-Forwarded-For": "203.0.113.7" }))
    ).toBe("203.0.113.7");
    expect(clientIpFromHeaders(new Headers({ "X-Real-IP": "198.51.100.4" }))).toBe(
      "198.51.100.4"
    );
  });

  it("falls back to x-real-ip when x-forwarded-for is absent", () => {
    expect(
      clientIpFromHeaders(new Headers({ "x-real-ip": "198.51.100.4" }))
    ).toBe("198.51.100.4");
  });

  it("falls back to x-real-ip when x-forwarded-for is empty or whitespace-only", () => {
    expect(
      clientIpFromHeaders(
        new Headers({ "x-forwarded-for": "", "x-real-ip": "198.51.100.4" })
      )
    ).toBe("198.51.100.4");
    expect(
      clientIpFromHeaders(
        new Headers({ "x-forwarded-for": "   ", "x-real-ip": "198.51.100.4" })
      )
    ).toBe("198.51.100.4");
  });

  it("does not trust a non-final entry when the chain ends in an empty element", () => {
    // "1.2.3.4," is malformed; the final (verified) position is empty, so the
    // untrusted "1.2.3.4" must NOT be promoted into the rate-limit key.
    const headers = new Headers({ "x-forwarded-for": "1.2.3.4," });
    expect(clientIpFromHeaders(headers)).not.toBe("1.2.3.4");
    expect(clientIpFromHeaders(headers)).toBe("unknown");
  });

  it("returns the constant 'unknown' when no forwarding headers are present", () => {
    // A constant, not a per-request value: unattributable traffic must share a
    // single bucket rather than each get its own fresh budget.
    expect(clientIpFromHeaders(new Headers())).toBe("unknown");
    expect(clientIpFromHeaders(new Headers())).toBe(
      clientIpFromHeaders(new Headers())
    );
  });
});
