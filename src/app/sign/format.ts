// Deterministic UTC formatting shared by the /sign server component and the
// client signing form.
//
// Why hand-rolled instead of Intl/toLocaleString: the signature timestamp is a
// legal record. It must read identically on the server-rendered HTML and after
// hydration (no locale/timezone drift → no hydration mismatch), and it must be
// unambiguous to a DOL investigator reading the exported audit file. Always
// UTC, always ISO-ordered, always tabular.

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** `2026-04-16 18:42 UTC` — full stamp for signature and expiry records. */
export function formatUtcStamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
  );
}

/** `2026-04-16` — date-only, for expiry copy where the clock time is noise. */
export function formatUtcDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

/** `$2.13` — money always renders mono/tabular per the visual brief. */
export function formatUsd(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

/**
 * `REC-2026-0416-8F2C` — the record ID stamped on the notice card. Derived
 * from immutable values (notice id + creation date) so the same notice always
 * carries the same mark across page, email, and audit export.
 */
export function buildRecordId(noticeId: string, createdAt: string | null): string {
  const d = createdAt ? new Date(createdAt) : new Date(0);
  const safe = Number.isNaN(d.getTime()) ? new Date(0) : d;
  const suffix = noticeId.replace(/[^A-Za-z0-9]/g, "").slice(-4).toUpperCase() || "0000";
  return `REC-${safe.getUTCFullYear()}-${pad(safe.getUTCMonth() + 1)}${pad(safe.getUTCDate())}-${suffix}`;
}
