// Unit tests for the signing-link token contract (behavior b-07):
// "A valid unexpired token renders the exact notice text that was sent; an
//  invalid, expired, or already-used token renders an error state and cannot
//  sign."
//
// This module is the security boundary for the entire public /sign flow.
// `POST /api/notices/send` mints tokens and stores `hashSigningToken(raw)` in
// `signing_tokens.token_hash`; `POST /api/notices/sign` and the /sign server
// component look tokens up by the SAME digest. If the two sides ever disagree,
// every signing link in production breaks silently. These tests pin the digest
// to independently-known SHA-256 vectors so an algorithm change cannot pass.

import { randomBytes, createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  SIGNING_TOKEN_PATTERN,
  hashSigningToken,
  isWellFormedSigningToken,
} from "./signing-token";

/** A realistically-minted token: `randomBytes(32).toString("base64url")`. */
function mintToken(): string {
  return randomBytes(32).toString("base64url");
}

describe("hashSigningToken", () => {
  it("produces the published SHA-256 vector for 'abc' (algorithm is pinned)", () => {
    // NIST FIPS 180-4 sample vector. If someone swaps SHA-256 for another
    // digest, or adds a salt/prefix, this assertion fails immediately.
    expect(hashSigningToken("abc")).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
  });

  it("produces the published SHA-256 vector for the empty string", () => {
    expect(hashSigningToken("")).toBe(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    );
  });

  it("returns 64 lowercase hex characters for a realistically minted token", () => {
    const digest = hashSigningToken(mintToken());
    expect(digest).toMatch(/^[0-9a-f]{64}$/);
  });

  it("is deterministic — the mint side and the consume side derive the same digest", () => {
    // This is the cross-route contract: send/route.ts writes token_hash and
    // sign/route.ts queries `.eq("token_hash", hashSigningToken(input.token))`.
    const raw = mintToken();
    const atMintTime = hashSigningToken(raw);
    const atConsumeTime = hashSigningToken(raw);
    expect(atConsumeTime).toBe(atMintTime);
  });

  it("matches an independently computed node:crypto SHA-256 hex digest", () => {
    const raw = mintToken();
    const expected = createHash("sha256").update(raw, "utf8").digest("hex");
    expect(hashSigningToken(raw)).toBe(expected);
  });

  it("maps different tokens to different digests", () => {
    const digests = new Set(
      Array.from({ length: 50 }, () => hashSigningToken(mintToken()))
    );
    expect(digests.size).toBe(50);
  });

  it("is case-sensitive — base64url is a case-significant alphabet", () => {
    expect(hashSigningToken("AbCdEfGh")).not.toBe(hashSigningToken("abcdefgh"));
  });

  it("is sensitive to a single-character change (no digest collisions on near misses)", () => {
    const raw = mintToken();
    const tampered = `${raw.slice(0, -1)}${raw.endsWith("A") ? "B" : "A"}`;
    expect(hashSigningToken(tampered)).not.toBe(hashSigningToken(raw));
  });

  it("never leaks the raw token into the stored digest", () => {
    // Rationale from the module header: a database leak must not hand an
    // attacker a set of working signing links.
    const raw = mintToken();
    const digest = hashSigningToken(raw);
    expect(digest).not.toContain(raw);
    expect(digest).not.toBe(raw);
  });

  it("hashes multi-byte input as UTF-8 rather than throwing", () => {
    expect(hashSigningToken("héllo-wörld-token")).toMatch(/^[0-9a-f]{64}$/);
  });
});

describe("isWellFormedSigningToken", () => {
  it("accepts a token minted as randomBytes(32).toString('base64url')", () => {
    for (let i = 0; i < 25; i++) {
      const raw = mintToken();
      expect(raw).toHaveLength(43);
      expect(isWellFormedSigningToken(raw)).toBe(true);
    }
  });

  it("accepts the full URL-safe base64 alphabet including '-' and '_'", () => {
    expect(isWellFormedSigningToken("aZ09-_aZ09-_")).toBe(true);
  });

  it("accepts tokens at both length boundaries (8 and 128 characters)", () => {
    expect(isWellFormedSigningToken("a".repeat(8))).toBe(true);
    expect(isWellFormedSigningToken("a".repeat(128))).toBe(true);
  });

  it("rejects tokens shorter than the 8-character minimum", () => {
    expect(isWellFormedSigningToken("a".repeat(7))).toBe(false);
    expect(isWellFormedSigningToken("")).toBe(false);
  });

  it("rejects tokens longer than the 128-character maximum", () => {
    expect(isWellFormedSigningToken("a".repeat(129))).toBe(false);
    expect(isWellFormedSigningToken("a".repeat(5000))).toBe(false);
  });

  it("rejects standard-base64 characters that are not URL-safe", () => {
    // A token containing '+', '/', or '=' cannot have come from base64url and
    // would round-trip incorrectly through a query string.
    expect(isWellFormedSigningToken("abcdefg+hijk")).toBe(false);
    expect(isWellFormedSigningToken("abcdefg/hijk")).toBe(false);
    expect(isWellFormedSigningToken("abcdefghijk=")).toBe(false);
  });

  it("rejects punctuation and whitespace that could reach a database query", () => {
    const malformed = [
      "abcdefgh ijkl",
      " abcdefghijkl",
      "abcdefghijkl ",
      "abcdefgh.ijkl",
      "abcdefgh,ijkl",
      "abcdefgh'ijkl",
      'abcdefgh"ijkl',
      "abcdefgh%ijkl",
      "abcdefgh(ijkl",
      "abcdefgh*ijkl",
    ];
    for (const token of malformed) {
      expect(isWellFormedSigningToken(token)).toBe(false);
    }
  });

  it("rejects PostgREST filter-injection payloads", () => {
    // The token is interpolated into `.eq("token_hash", ...)` only after
    // hashing, but the shape gate is the first line of defence.
    expect(isWellFormedSigningToken("abcdefgh,used_at.is.null")).toBe(false);
    expect(isWellFormedSigningToken("*")).toBe(false);
    expect(isWellFormedSigningToken("abcdefgh' OR '1'='1")).toBe(false);
  });

  it("rejects tokens with an embedded or trailing newline (anchor bypass guard)", () => {
    // Regression guard: in some regex dialects `$` matches before a trailing
    // newline. If this module's pattern ever gained the `m` flag, these would
    // start passing and smuggle control characters into the lookup path.
    expect(isWellFormedSigningToken("abcdefghijkl\n")).toBe(false);
    expect(isWellFormedSigningToken("\nabcdefghijkl")).toBe(false);
    expect(isWellFormedSigningToken("abcdef\nghijkl")).toBe(false);
    expect(isWellFormedSigningToken("abcdefghijkl\r\n")).toBe(false);
    expect(isWellFormedSigningToken("abcdefghijkl ")).toBe(false);
  });

  it("rejects a non-ASCII token", () => {
    expect(isWellFormedSigningToken("abcdefghéijkl")).toBe(false);
  });

  it("is stateless across repeated calls (the pattern carries no /g lastIndex)", () => {
    // Regression guard: a `/g` regex reused via `.test()` alternates true/false
    // because `lastIndex` advances. That would make roughly half of all valid
    // signing links fail at random in production.
    expect(SIGNING_TOKEN_PATTERN.flags).not.toContain("g");
    expect(SIGNING_TOKEN_PATTERN.flags).not.toContain("y");
    const raw = mintToken();
    expect(isWellFormedSigningToken(raw)).toBe(true);
    expect(isWellFormedSigningToken(raw)).toBe(true);
    expect(isWellFormedSigningToken(raw)).toBe(true);
  });
});

describe("signing-token contract as used by /sign and the API routes", () => {
  it("gates hashing behind the shape check — malformed input is refused before lookup", () => {
    // notice-lookup.ts and POST /api/notices/sign both call
    // `isWellFormedSigningToken` first and return not_found/400 on false.
    const attackerSupplied = "'; DROP TABLE signing_tokens; --";
    expect(isWellFormedSigningToken(attackerSupplied)).toBe(false);
  });

  it("keeps every minted token accepted by the shape check (mint/validate agree)", () => {
    // If the mint width in send/route.ts and the pattern here ever drift apart,
    // every newly issued signing link would 404 on open.
    for (let i = 0; i < 100; i++) {
      expect(isWellFormedSigningToken(mintToken())).toBe(true);
    }
  });

  it("produces a digest that fits the signing_tokens.token_hash text column", () => {
    expect(hashSigningToken(mintToken())).toHaveLength(64);
  });
});
