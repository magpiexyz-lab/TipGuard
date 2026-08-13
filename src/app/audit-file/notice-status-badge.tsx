import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { CoverIndexEntry } from "./audit-file-contract";

/**
 * Status chip vocabulary from the visual brief: DRAFT (ink-soft) /
 * SENT (brass) / SIGNED (seal), 11px Plex Mono uppercase on a 12% tint.
 * `--brass` is never used as text on paper — SENT uses `--brass-deep`.
 */
const STATUS_STYLES: Record<CoverIndexEntry["noticeStatus"], string> = {
  none: "bg-muted text-ink-soft dark:text-muted-foreground",
  draft: "bg-muted text-ink-soft dark:text-muted-foreground",
  sent: "bg-brass/12 text-brass-deep dark:text-brass",
  signed: "bg-seal/12 text-seal dark:text-seal-soft",
};

const STATUS_LABELS: Record<CoverIndexEntry["noticeStatus"], string> = {
  none: "No notice",
  draft: "Draft",
  sent: "Sent",
  signed: "Signed",
};

export function NoticeStatusBadge({
  status,
}: {
  status: CoverIndexEntry["noticeStatus"];
}) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "h-6 rounded-md border-transparent font-mono text-[11px] tracking-[0.1em] uppercase",
        STATUS_STYLES[status]
      )}
    >
      {STATUS_LABELS[status]}
    </Badge>
  );
}
