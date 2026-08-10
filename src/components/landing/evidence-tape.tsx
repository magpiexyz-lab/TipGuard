import { Marquee } from "@/components/magicui/marquee";
import { cn } from "@/lib/utils";
import { VAULT_TAPE } from "./content";

const STATUS_STYLE: Record<string, string> = {
  SIGNED: "bg-seal/15 text-seal-soft",
  SENT: "bg-brass/15 text-brass",
  DRAFT: "bg-paper/10 text-paper/70",
};

/**
 * Evidence tape — a thin ink band of vault records advancing between the
 * feature bento and the price.
 *
 * These are format illustrations, not customer records: the band shows what a
 * stored acknowledgment looks like (record id, status, state, rule version,
 * UTC stamp), which is exactly the shape an investigator asks for. Hovering
 * pauses the tape.
 */
export function EvidenceTape() {
  return (
    <section className="surface-ink relative overflow-hidden py-10" aria-label="What the vault stores">
      <div className="mx-auto mb-6 max-w-[1160px] px-5 sm:px-8">
        <p className="font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-brass">
          What the vault stores · record format
        </p>
      </div>

      <Marquee durationSeconds={64} gap="1.25rem">
        {VAULT_TAPE.map((record) => (
          <div
            key={record.id}
            className="flex shrink-0 items-center gap-4 rounded-lg border border-paper/10 px-5 py-3"
          >
            <span className="figure text-xs text-paper/80">{record.id}</span>
            <span
              className={cn(
                "rounded-sm px-2 py-0.5 font-mono text-[11px] font-medium uppercase tracking-[0.1em]",
                STATUS_STYLE[record.status]
              )}
            >
              {record.status}
            </span>
            <span className="figure whitespace-nowrap text-[11px] text-paper/60">
              {record.meta}
            </span>
          </div>
        ))}
      </Marquee>
    </section>
  );
}
