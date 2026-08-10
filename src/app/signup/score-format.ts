// Presentation helpers for the carried audit-readiness record on /signup.
//
// The record itself is owned by the producer: `@/app/score/pending-score`
// (localStorage, versioned, TTL-enforced). Nothing here duplicates that
// contract — these are display-only derivations used by the signup evidence
// rail and the mobile carry strip.

/** `REC-2026-0807` — the dossier stamp shown on evidence surfaces. */
export function recordStamp(savedAt: string): string {
  const date = new Date(savedAt);
  if (Number.isNaN(date.getTime())) return "REC-UNDATED";
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `REC-${date.getUTCFullYear()}-${month}${day}`;
}

/** Compliance ramp band for the readiness figure (ember → brass → seal). */
export function scoreBand(score: number): "critical" | "at-risk" | "clear" {
  if (score < 50) return "critical";
  if (score < 80) return "at-risk";
  return "clear";
}

export function formatUsd(value: number): string {
  return `$${Math.round(value).toLocaleString("en-US")}`;
}
