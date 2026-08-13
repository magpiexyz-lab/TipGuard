// Signing-link token contract (behavior b-07).
//
// SECURITY MODEL — read before changing anything in this file.
//
// `/sign` is a public route (listed in `src/proxy.ts` publicPaths). The person
// signing is a restaurant employee with no TipGuard account and no session, so
// the ONLY authorization material is the opaque token carried in the URL that
// was emailed to them. Consequences:
//
//   1. The raw token is NEVER stored. `signing_tokens.token_hash` holds the
//      SHA-256 hex digest of the raw token. A database leak therefore does not
//      hand an attacker a set of working signing links.
//   2. Validity (existence, `expires_at`, `used_at`) is resolved SERVER-SIDE
//      only — in the `/sign` server component (see `notice-lookup.ts`) and
//      again inside `POST /api/notices/sign` before the signature row is
//      written. The client is never asked, and never trusted, for any of it.
//   3. Re-validation on submit is not optional. A token can expire or be
//      consumed between page render and form submit.
//
// CROSS-AGENT CONTRACT: `POST /api/notices/send` (which mints tokens) and
// `POST /api/notices/sign` (which consumes them) MUST use `hashSigningToken`
// from this module so the two sides agree on the digest. If a later change
// moves this helper to `src/lib/signing-token.ts`, move it wholesale — do not
// fork a second hashing implementation.

import { createHash } from "node:crypto";

/**
 * Shape of a mintable signing token: URL-safe base64 alphabet, long enough
 * that guessing is infeasible. Tokens should be generated as
 * `randomBytes(32).toString("base64url")` (43 chars).
 */
export const SIGNING_TOKEN_PATTERN = /^[A-Za-z0-9_-]{8,128}$/;

/** Cheap shape check so malformed input never reaches a database query. */
export function isWellFormedSigningToken(token: string): boolean {
  return SIGNING_TOKEN_PATTERN.test(token);
}

/** SHA-256 hex digest — the value stored in `signing_tokens.token_hash`. */
export function hashSigningToken(token: string): string {
  return createHash("sha256").update(token, "utf8").digest("hex");
}
