/**
 * Route-level loading state for /sign.
 *
 * The page is `force-dynamic` and resolves the signing token against the
 * database on every request, so there is always a server round-trip before
 * anything renders. Skeletons are ruled oat bars on the 32px ledger rhythm and
 * enter top-to-bottom on a 55ms stagger (visual brief: "ledger rows enter in
 * sequence like a printer, not like a bubble field"). Global reduced-motion
 * handling in globals.css collapses the animation to a static final state.
 */
export default function SignLoading() {
  const rows = [0, 1, 2, 3, 4, 5];

  return (
    <div className="relative min-h-screen overflow-x-hidden" aria-hidden="true">
      <div
        className="texture-rule bloom-brass pointer-events-none absolute inset-x-0 top-0 h-[380px]"
        style={{
          maskImage: "linear-gradient(to bottom, black, transparent)",
          WebkitMaskImage: "linear-gradient(to bottom, black, transparent)",
        }}
      />

      <div className="relative mx-auto w-full max-w-[760px] px-5 pt-10 pb-20 sm:px-8 sm:pt-16">
        <div className="flex items-start justify-between gap-4">
          <div className="w-full max-w-[16rem] space-y-2.5">
            <div className="h-2.5 w-40 animate-pulse rounded-sm bg-foreground/10" />
            <div className="h-3.5 w-56 animate-pulse rounded-sm bg-foreground/10" />
          </div>
          <div className="h-6 w-32 animate-pulse rounded-md bg-foreground/10" />
        </div>

        <div className="mt-8 space-y-3.5">
          <div className="h-9 w-[85%] animate-pulse rounded-sm bg-foreground/10 sm:h-12" />
          <div className="h-9 w-[55%] animate-pulse rounded-sm bg-foreground/10 sm:h-12" />
        </div>

        <div className="mt-6 space-y-2.5">
          <div className="h-3.5 w-full animate-pulse rounded-sm bg-foreground/5" />
          <div className="h-3.5 w-[78%] animate-pulse rounded-sm bg-foreground/5" />
        </div>

        <div className="mt-12 overflow-hidden rounded-xl bg-paper-raised elev-1">
          <div className="border-b border-border px-5 py-4 sm:px-7">
            <div className="h-2.5 w-28 animate-pulse rounded-sm bg-foreground/10" />
            <div className="mt-2.5 h-3.5 w-40 animate-pulse rounded-sm bg-foreground/10" />
          </div>

          <div className="grid grid-cols-2 gap-px bg-border sm:grid-cols-4">
            {[0, 1, 2, 3].map((cell) => (
              <div key={cell} className="bg-paper-raised px-5 py-4 sm:px-4">
                <div
                  className="h-2.5 w-16 animate-pulse rounded-sm bg-foreground/10"
                  style={{ animationDelay: `${cell * 55}ms` }}
                />
                <div
                  className="mt-2 h-4 w-20 animate-pulse rounded-sm bg-foreground/10"
                  style={{ animationDelay: `${cell * 55}ms` }}
                />
              </div>
            ))}
          </div>

          {/* Ruled document body — bars land on the 32px ledger rhythm. */}
          <div className="texture-rule border-t border-border px-5 py-6 sm:px-7 sm:py-8">
            <div className="space-y-[19px]">
              {rows.map((row) => (
                <div
                  key={row}
                  className="h-3 animate-pulse rounded-sm bg-foreground/5"
                  style={{
                    width: `${[92, 78, 96, 64, 88, 46][row]}%`,
                    animationDelay: `${row * 55}ms`,
                  }}
                />
              ))}
            </div>
          </div>
        </div>

        <div className="mt-12 overflow-hidden rounded-xl bg-paper-raised elev-1">
          <div className="border-b border-border px-5 py-5 sm:px-7">
            <div className="h-2.5 w-20 animate-pulse rounded-sm bg-foreground/10" />
            <div className="mt-3 h-6 w-64 animate-pulse rounded-sm bg-foreground/10" />
          </div>
          <div className="px-5 py-6 sm:px-7">
            <div className="h-3 w-36 animate-pulse rounded-sm bg-foreground/10" />
            <div className="mt-2.5 h-12 w-full animate-pulse rounded-lg bg-foreground/5" />
            <div className="mt-6 h-24 w-full animate-pulse rounded-lg bg-foreground/5" />
            <div className="mt-6 h-12 w-56 animate-pulse rounded-full bg-brass/20" />
          </div>
        </div>
      </div>
    </div>
  );
}
