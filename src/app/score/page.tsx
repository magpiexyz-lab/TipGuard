"use client";

// /score — free audit-readiness score (behaviors b-01 exit, b-02).
//
// PUBLIC ROUTE. No session, no gate: `/score` is listed in src/proxy.ts
// publicPaths and nothing on this page reads auth. That is the whole hook —
// an owner gets a real number before being asked for anything.
//
// Analytics (experiment/EVENTS.yaml):
//   score_started   — fires once, on the first answered question
//   score_completed — fires once, when the results surface renders
//
// The result is parked in localStorage by ./pending-score so /signup can attach
// it to the new account (b-03). See that file for the consumer contract.

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { trackScoreCompleted, trackScoreStarted } from "@/lib/events";
import { scoreAuditReadiness, type ScoringResult } from "@/lib/scoring";
import { cn } from "@/lib/utils";

import { Questionnaire } from "./questionnaire";
import { ScoreResults } from "./results";
import { savePendingScore } from "./pending-score";
import { toScoringInput, type Answers } from "./questions";

type Phase = "questions" | "scoring" | "results";

const SCORING_REVEAL_MS = 650;

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export default function ScorePage() {
  const [phase, setPhase] = useState<Phase>("questions");
  const [answers, setAnswers] = useState<Answers>({});
  const [result, setResult] = useState<ScoringResult | null>(null);
  const [attempt, setAttempt] = useState(0);

  const startedFired = useRef(false);
  const completedFired = useRef(false);
  const revealTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (revealTimer.current) clearTimeout(revealTimer.current);
    };
  }, []);

  // score_started — first answered question, exactly once per page life.
  const handleFirstAnswer = useCallback((first: Answers) => {
    if (startedFired.current) return;
    startedFired.current = true;
    trackScoreStarted({ state: first.state });
  }, []);

  const reveal = useCallback((finalAnswers: Answers, computed: ScoringResult) => {
    setResult(computed);
    setPhase("results");

    // score_completed — once, on results render.
    if (!completedFired.current) {
      completedFired.current = true;
      trackScoreCompleted({
        readiness_score: computed.score,
        gap_count: computed.gaps.length,
        state: finalAnswers.state ?? "OTHER",
        estimated_exposure_usd: computed.estimatedExposureUsd.high,
      });
    }

    // Handoff to /signup (b-03). Non-blocking and failure-tolerant.
    savePendingScore({
      state: finalAnswers.state ?? "OTHER",
      claimsTipCredit: finalAnswers.claimsTipCredit === "yes",
      staffCount: finalAnswers.staffCount ?? 0,
      result: computed,
    });
  }, []);

  const handleComplete = useCallback(
    (finalAnswers: Answers) => {
      setAnswers(finalAnswers);
      // Deterministic pure function — see src/lib/scoring.ts. Never a model call.
      const computed = scoreAuditReadiness(toScoringInput(finalAnswers));

      if (prefersReducedMotion()) {
        reveal(finalAnswers, computed);
        return;
      }
      setPhase("scoring");
      if (revealTimer.current) clearTimeout(revealTimer.current);
      revealTimer.current = setTimeout(() => reveal(finalAnswers, computed), SCORING_REVEAL_MS);
    },
    [reveal],
  );

  const handleRestart = useCallback(() => {
    completedFired.current = false;
    startedFired.current = false;
    setResult(null);
    setAnswers({});
    setPhase("questions");
    setAttempt((n) => n + 1);
    if (typeof window !== "undefined") window.scrollTo({ top: 0 });
  }, []);

  const showingResults = phase === "results" && result !== null;

  return (
    <div className="min-h-screen">
      {/* --- Ink authority band ------------------------------------------- */}
      <div className="surface-ink texture-rule bloom-brass">
        <div className="mx-auto max-w-[1120px] px-6 pb-4 pt-4">
          <Link
            href="/"
            className={cn(
              "inline-flex items-center gap-2 text-sm text-[#A8AF9B]",
              "transition-colors duration-[var(--duration-fast)] hover:text-[#ECE8DA]",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brass",
            )}
          >
            <ArrowLeft aria-hidden="true" className="size-4" />
            TipGuard
          </Link>

          <p className="eyebrow mt-4">Free audit-readiness score</p>

          {/* globals.css sets h1 tracking in fixed px (-2px), tuned for a 60px
              display size. Every hero h1 overrides it in em instead, so the
              tracking scales with the type rather than closing the word gaps
              up ("Howexposed") once the size drops. */}
          <h1 className="mt-2 max-w-3xl text-[26px] leading-[1.06] tracking-[-0.025em] text-[#ECE8DA] sm:text-[32px]">
            {showingResults
              ? "Your audit-readiness score"
              : "How exposed is your tip credit?"}
          </h1>

          <p className="mt-3 max-w-2xl text-base leading-[1.55] text-[#A8AF9B]">
            {showingResults
              ? "Scored against the items a wage-and-hour investigator opens with: signed notices, tip-pool composition, overtime basis, and new-hire process."
              : "Seven questions about how you actually run tipped pay. No account, no email, no sales call — you get the number, the ranked gaps, and an exposure range at the end."}
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2">
            {["About 2 minutes", "No account required", "Nothing sent to your staff"].map(
              (item) => (
                <span key={item} data-evidence className="text-xs text-[#A8AF9B]">
                  {item}
                </span>
              ),
            )}
          </div>
        </div>
      </div>

      {/* --- Phase surface -------------------------------------------------- */}
      {phase === "questions" ? (
        <Questionnaire
          key={attempt}
          onFirstAnswer={handleFirstAnswer}
          onComplete={handleComplete}
        />
      ) : null}

      {phase === "scoring" ? <ScoringSkeleton /> : null}

      {showingResults ? (
        <ScoreResults result={result} answers={answers} onRestart={handleRestart} />
      ) : null}
    </div>
  );
}

/**
 * Ruled skeleton on the 32px ledger rhythm, revealed top-to-bottom at a 55ms
 * stagger — the visual brief's loading treatment. Announced politely so a
 * screen-reader user is told the score is being assembled rather than hearing
 * silence between the last answer and the result.
 */
function ScoringSkeleton() {
  const lines = [
    "Resolving the state rule library",
    "Checking signed-notice coverage",
    "Checking tip-pool composition",
    "Checking the overtime basis",
    "Estimating back-pay exposure",
  ];

  return (
    <div className="mx-auto max-w-[1120px] px-6 pb-16 pt-8" aria-live="polite" aria-busy="true">
      <p className="eyebrow">Scoring</p>
      <h2 className="mt-3 text-2xl tracking-[-0.8px] sm:text-3xl sm:tracking-[-1.6px]">
        Assembling your file
      </h2>

      <div className="mt-6 grid gap-8 md:grid-cols-[240px_1fr]">
        <div
          className="aspect-square w-full max-w-[240px] animate-pulse rounded-full bg-muted"
          aria-hidden="true"
        />
        <ul className="space-y-0">
          {lines.map((line, index) => (
            <li
              key={line}
              className="flex h-8 items-center gap-4 border-b border-border animate-pulse"
              style={{ animationDelay: `${index * 55}ms` }}
            >
              <span className="h-2 w-2 shrink-0 rounded-full bg-brass" aria-hidden="true" />
              <span className="text-sm text-muted-foreground">{line}</span>
              <span className="ml-auto h-2 w-16 rounded-full bg-muted" aria-hidden="true" />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
