// Anonymous-score handoff contract: /score  ->  /signup  ->  /auth/callback (b-02 -> b-03).
//
// The free questionnaire runs with no session, so the result has nowhere to live
// server-side until an account exists. It is parked in localStorage under a
// versioned key and picked up by the signup flow, which POSTs it onto the new
// account row (accounts.readiness_score / accounts.gap_list in src/lib/types.ts).
//
// WHY localStorage AND NOT sessionStorage: the Google OAuth leg of signup leaves
// the origin entirely and can return in a different tab. sessionStorage is
// per-tab and would silently drop the score for every OAuth signup, which is
// exactly the conversion path h-03 measures.
//
// CONSUMER CONTRACT (signup / auth-callback agents):
//   import { readPendingScore, clearPendingScore } from "@/app/score/pending-score";
//   const pending = readPendingScore();          // null when the user skipped /score
//   ...attach pending.readinessScore + pending.gaps to the account...
//   clearPendingScore();                          // after a successful attach ONLY
//
// The payload is non-sensitive (no PII: no name, email, or address) and expires
// on its own after PENDING_SCORE_TTL_MS so a stale score from a previous session
// can never be attached to an unrelated account.

import type { GapFinding, ScoringResult } from "@/lib/scoring";

export const PENDING_SCORE_STORAGE_KEY = "tipguard.pending_score.v1";

/** 7 days — long enough to survive an OAuth detour or a "finish it tonight". */
export const PENDING_SCORE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export interface PendingScore {
  version: 1;
  /** ISO-8601 UTC. Used for TTL enforcement and for the dashboard "scored on" stamp. */
  savedAt: string;
  /** Two-letter state code, or "OTHER" when the state is outside the rule library. */
  state: string;
  claimsTipCredit: boolean;
  staffCount: number;
  /** 0-100, straight from scoreAuditReadiness(). */
  readinessScore: number;
  /** Ranked most-severe-first, straight from scoreAuditReadiness(). */
  gaps: GapFinding[];
  estimatedExposureUsd: { low: number; high: number };
}

function storage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    // Private mode / sandboxed iframe / storage disabled. The score still
    // renders — it just cannot be carried into signup.
    return null;
  }
}

export function savePendingScore(input: {
  state: string;
  claimsTipCredit: boolean;
  staffCount: number;
  result: ScoringResult;
}): void {
  const store = storage();
  if (!store) return;

  const payload: PendingScore = {
    version: 1,
    savedAt: new Date().toISOString(),
    state: input.state,
    claimsTipCredit: input.claimsTipCredit,
    staffCount: input.staffCount,
    readinessScore: input.result.score,
    gaps: input.result.gaps,
    estimatedExposureUsd: input.result.estimatedExposureUsd,
  };

  try {
    store.setItem(PENDING_SCORE_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Quota exceeded — the score is ~1 kB, so this is effectively unreachable,
    // but a failed handoff must never break the results render.
  }
}

export function readPendingScore(): PendingScore | null {
  const store = storage();
  if (!store) return null;

  let raw: string | null;
  try {
    raw = store.getItem(PENDING_SCORE_STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as PendingScore;
    if (parsed?.version !== 1 || typeof parsed.readinessScore !== "number") {
      clearPendingScore();
      return null;
    }
    if (Date.now() - new Date(parsed.savedAt).getTime() > PENDING_SCORE_TTL_MS) {
      clearPendingScore();
      return null;
    }
    return parsed;
  } catch {
    clearPendingScore();
    return null;
  }
}

export function clearPendingScore(): void {
  const store = storage();
  if (!store) return;
  try {
    store.removeItem(PENDING_SCORE_STORAGE_KEY);
  } catch {
    // Nothing to do — the TTL check will discard it on the next read.
  }
}
