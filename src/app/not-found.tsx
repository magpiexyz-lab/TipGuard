import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function NotFound() {
  // <div>, not <main>: src/app/layout.tsx owns the single `main` landmark for
  // every route (axe landmark-no-duplicate-main / landmark-one-main).
  return (
    <div className="flex min-h-screen items-center justify-center px-6 py-24">
      <div className="w-full max-w-lg text-center">
        <p className="eyebrow text-brass-deep">Error 404</p>
        <h1 className="mt-4 font-display text-4xl font-bold tracking-tight sm:text-5xl">
          This page isn&apos;t in the file
        </h1>
        <p className="mt-4 text-ink-soft">
          The record you asked for doesn&apos;t exist — or it moved. Your saved
          notices and signatures are unaffected.
        </p>
        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Link
            href="/"
            className={cn(buttonVariants(), "h-11 rounded-full px-6 text-base")}
          >
            Back to TipGuard
          </Link>
          <Link
            href="/score"
            className={cn(
              buttonVariants({ variant: "outline" }),
              "h-11 px-6 text-base"
            )}
          >
            Check my audit readiness
          </Link>
        </div>
      </div>
    </div>
  );
}
