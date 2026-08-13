"use client";

import { useEffect } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface the digest in the browser console so a support request can quote
    // it. The message itself is not rendered — it can carry internal detail.
    console.error("Unhandled application error", error);
  }, [error]);

  // <div>, not <main>: src/app/layout.tsx owns the single `main` landmark for
  // every route (axe landmark-no-duplicate-main / landmark-one-main).
  return (
    <div className="flex min-h-screen items-center justify-center px-6 py-24">
      <div className="w-full max-w-lg text-center">
        <p className="eyebrow text-brass-deep">Something broke</p>
        <h1 className="mt-4 font-display text-4xl font-bold tracking-tight sm:text-5xl">
          We couldn&apos;t load that record
        </h1>
        <p className="mt-4 text-ink-soft">
          Nothing was changed or deleted. Try again — if it keeps happening,
          quote the reference below when you contact us.
        </p>
        {error.digest ? (
          <p className="mt-6 font-mono text-sm tabular-nums text-ink-soft">
            REF-{error.digest}
          </p>
        ) : null}
        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Button
            onClick={reset}
            className="h-11 rounded-full px-6 text-base"
          >
            Try again
          </Button>
          <a
            href="/dashboard"
            className={cn(
              buttonVariants({ variant: "outline" }),
              "h-11 px-6 text-base"
            )}
          >
            Back to dashboard
          </a>
        </div>
      </div>
    </div>
  );
}
