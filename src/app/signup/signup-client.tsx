"use client";

import { useEffect, useRef, useState } from "react";
import { trackSignupStart } from "@/lib/events";
import { ScoreCarryRail } from "./score-carry-rail";
import { SignupForm } from "./signup-form";
import { readPendingScore, type PendingScore } from "@/app/score/pending-score";

/**
 * Client shell for `/signup`.
 *
 * Owns the two things the server cannot: the `signup_start` mount event and the
 * one read of the anonymous score carried over from `/score` (localStorage,
 * owned by `@/app/score/pending-score`). Both the form and the evidence rail
 * render from that single read, so the figure the owner sees is exactly the
 * record that gets attached to the account (b-03).
 *
 * `undefined` = not read yet (renders a skeleton), `null` = no carried score.
 */
export function SignupClient() {
  const [pending, setPending] = useState<PendingScore | null | undefined>(undefined);
  const startFired = useRef(false);

  useEffect(() => {
    setPending(readPendingScore());
  }, []);

  useEffect(() => {
    // Ref guard: React StrictMode double-invokes effects in development, and
    // signup_start is the activate-stage entry counter — it must fire once.
    if (startFired.current) return;
    startFired.current = true;
    trackSignupStart({ auth_method: "both" });
  }, []);

  return (
    <div className="grid lg:grid-cols-[1fr_minmax(24rem,44%)]">
      <div className="flex flex-col justify-center px-6 py-16 sm:px-12 lg:px-14 lg:py-24">
        <div className="mx-auto w-full max-w-md">
          <p className="eyebrow">Step 4 of 6 &middot; Create account</p>
          <h1 className="mt-5 font-display text-4xl leading-[1.04] tracking-[-2px] sm:text-5xl">
            {pending
              ? "Keep your score. Close the gaps."
              : "Open your tip-credit file"}
          </h1>
          <p className="mt-5 text-lg leading-[1.55] text-muted-foreground">
            {pending
              ? "Your account holds the score, the gap list, and every notice you send from here — dated, signed, and exportable."
              : "One account holds your roster, your state-specific notices, the signed acknowledgments, and the export you hand an investigator."}
          </p>

          <SignupForm pending={pending} />
        </div>
      </div>

      <ScoreCarryRail pending={pending} />
    </div>
  );
}
