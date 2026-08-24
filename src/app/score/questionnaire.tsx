"use client";

// The seven-question audit-readiness questionnaire (b-02).
//
// One question per step: the completion rate through this form IS hypothesis
// h-02, so the form is built to hold attention — a single decision per screen,
// selection auto-advances, and the left rail keeps every prior answer one click
// away so nobody has to restart to change their mind.

import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

import { RadioCards } from "./radio-cards";
import {
  MAX_STAFF_COUNT,
  MIN_STAFF_COUNT,
  answerLabel,
  isAnswered,
  visibleQuestions,
  type Answers,
  type Question,
} from "./questions";

const ADVANCE_DELAY_MS = 260;

/**
 * Four of the seven questions are only asked of someone who claims the tip
 * credit, so before question 2 is answered `visibleQuestions` legitimately
 * returns 3. Rendering that raw made the form open on "Question 1 of 3" and
 * "0 / 3" directly beneath a hero promising *seven* questions — then jump to 7
 * on the next click, which reads as a bait rather than a branch.
 *
 * So until the branch resolves we project the full path (the tip-credit answer
 * is "yes" for anyone this product is for). Answering "no" then *shortens* the
 * questionnaire, and a path getting shorter reads as relief, never as a trick.
 */
function projectedSteps(answers: Answers): Question[] {
  return visibleQuestions(
    answers.claimsTipCredit ? answers : { ...answers, claimsTipCredit: "yes" },
  );
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function Questionnaire({
  onFirstAnswer,
  onComplete,
}: {
  onFirstAnswer: (answers: Answers) => void;
  onComplete: (answers: Answers) => void;
}) {
  const [answers, setAnswers] = useState<Answers>({});
  const [stepIndex, setStepIndex] = useState(0);
  const [staffInput, setStaffInput] = useState("");
  const [staffError, setStaffError] = useState<string | null>(null);

  const advanceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const mounted = useRef(false);

  const steps = projectedSteps(answers);
  const safeIndex = Math.min(stepIndex, steps.length - 1);
  const current = steps[safeIndex];
  const answeredCount = steps.filter((question) => isAnswered(question, answers)).length;
  const isLastStep = safeIndex === steps.length - 1;

  useEffect(() => {
    return () => {
      if (advanceTimer.current) clearTimeout(advanceTimer.current);
    };
  }, []);

  // Move focus to the new question so keyboard and screen-reader users are not
  // stranded at the bottom of the previous one after an auto-advance.
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    headingRef.current?.focus();
  }, [safeIndex]);

  function commit(next: Answers) {
    const hadAnyAnswer = Object.keys(answers).length > 0;
    setAnswers(next);
    if (!hadAnyAnswer) onFirstAnswer(next);
  }

  function handleChoice(value: string) {
    const next: Answers = { ...answers, [current.id]: value };
    commit(next);
    setStaffError(null);

    const nextSteps = projectedSteps(next);
    if (safeIndex >= nextSteps.length - 1) return;

    if (prefersReducedMotion()) {
      setStepIndex(safeIndex + 1);
      return;
    }
    if (advanceTimer.current) clearTimeout(advanceTimer.current);
    advanceTimer.current = setTimeout(() => setStepIndex(safeIndex + 1), ADVANCE_DELAY_MS);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const parsed = Number.parseInt(staffInput, 10);
    if (!Number.isFinite(parsed) || parsed < MIN_STAFF_COUNT || parsed > MAX_STAFF_COUNT) {
      setStaffError(
        `Enter a whole number between ${MIN_STAFF_COUNT} and ${MAX_STAFF_COUNT}. This scales the exposure estimate.`,
      );
      return;
    }
    setStaffError(null);
    const next: Answers = { ...answers, staffCount: parsed };
    commit(next);
    onComplete(next);
  }

  return (
    <div className="mx-auto grid max-w-[1120px] gap-8 px-6 pb-16 pt-4 lg:grid-cols-[210px_1fr] lg:gap-10">
      {/* --- Left rail: the ledger index of every question ----------------- */}
      <div className="lg:sticky lg:top-6 lg:self-start">
        {/* The rail itself is desktop-only, so the label goes with it — below
            lg it was an "Audit checklist" heading standing over nothing. */}
        <p className="eyebrow hidden lg:block">Audit checklist</p>
        <ol aria-label="Questionnaire progress" className="mt-3 hidden lg:block">
          {steps.map((question, index) => {
            const answered = isAnswered(question, answers);
            const active = index === safeIndex;
            const reachable = answered || index <= answeredCount;
            return (
              <li key={question.id} className="border-b border-border last:border-b-0">
                <button
                  type="button"
                  disabled={!reachable}
                  onClick={() => {
                    if (advanceTimer.current) clearTimeout(advanceTimer.current);
                    setStepIndex(index);
                  }}
                  className={cn(
                    "flex w-full items-start gap-2.5 py-2 pl-3 pr-1 text-left",
                    "border-l-2 transition-colors duration-[var(--duration-fast)]",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brass",
                    active ? "border-l-brass" : "border-l-transparent",
                    reachable ? "hover:border-l-brass" : "cursor-not-allowed opacity-55",
                  )}
                >
                  <span
                    data-evidence
                    aria-hidden="true"
                    className={cn(
                      "mt-0.5 text-xs",
                      active ? "text-brass-deep dark:text-brass" : "text-muted-foreground",
                    )}
                  >
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span
                      className={cn(
                        "block text-sm leading-tight",
                        active ? "font-medium text-foreground" : "text-muted-foreground",
                      )}
                    >
                      {question.railLabel}
                    </span>
                    {answered ? (
                      <span className="mt-1 flex items-center gap-1 text-xs leading-tight text-seal dark:text-seal-soft">
                        <Check aria-hidden="true" className="size-3 shrink-0" />
                        <span className="truncate">{answerLabel(question, answers)}</span>
                      </span>
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        <div className="mt-4 lg:mt-5">
          <div className="flex items-baseline justify-between">
            <span className="eyebrow">Progress</span>
            <span data-evidence className="text-sm text-muted-foreground">
              {answeredCount} / {steps.length}
            </span>
          </div>
          <Progress
            value={(answeredCount / steps.length) * 100}
            aria-label="Questionnaire progress"
            className="mt-3"
          />
        </div>
      </div>

      {/* --- Question card ------------------------------------------------- */}
      <div>
        <div className="rounded-xl bg-card p-5 ring-1 ring-foreground/10">
          <p className="eyebrow">
            Question {safeIndex + 1} of {steps.length}
          </p>

          <h2
            ref={headingRef}
            tabIndex={-1}
            className="mt-2 text-xl leading-tight tracking-[-0.025em] [word-spacing:0.06em] outline-none sm:text-[26px] sm:leading-[1.12]"
          >
            {current.prompt}
          </h2>

          <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-muted-foreground">
            {current.help}
          </p>

          <div className="mt-4">
            {current.kind === "choice" && current.options ? (
              <RadioCards
                options={current.options}
                value={(answers[current.id] as string) ?? null}
                onChange={handleChoice}
                ariaLabel={current.prompt}
                columns={current.columns ?? 1}
              />
            ) : (
              <form onSubmit={handleSubmit} noValidate>
                <Label htmlFor="staff-count" className="text-base">
                  Tipped employees
                </Label>
                <Input
                  id="staff-count"
                  name="staffCount"
                  type="number"
                  inputMode="numeric"
                  min={MIN_STAFF_COUNT}
                  max={MAX_STAFF_COUNT}
                  step={1}
                  autoComplete="off"
                  placeholder="18"
                  value={staffInput}
                  onChange={(event) => setStaffInput(event.target.value)}
                  aria-invalid={staffError ? true : undefined}
                  aria-describedby={staffError ? "staff-count-error" : undefined}
                  className="mt-2 h-11 max-w-[200px] text-base md:text-base"
                />
                {staffError ? (
                  <p
                    id="staff-count-error"
                    role="alert"
                    className="mt-3 max-w-md text-sm leading-relaxed text-ember dark:text-ember-soft"
                  >
                    {staffError}
                  </p>
                ) : null}

                <Button
                  type="submit"
                  className="mt-7 h-11 rounded-full px-6 text-base font-medium transition-transform duration-[var(--duration-fast)] ease-[var(--ease-stamp)] hover:-translate-y-0.5"
                >
                  See my audit-readiness score
                  <ArrowRight aria-hidden="true" className="size-4" />
                </Button>
              </form>
            )}
          </div>

          {/* Evidence note — the statutory grounding for the question asked. */}
          <div className="mt-5 border-t border-border pt-4">
            <p className="text-sm leading-relaxed text-muted-foreground">{current.note}</p>
            <p data-evidence className="mt-2 text-xs text-brass-deep dark:text-brass">
              {current.citation}
            </p>
          </div>
        </div>

        <div className="mt-4 flex items-center justify-between">
          <Button
            type="button"
            variant="ghost"
            disabled={safeIndex === 0}
            onClick={() => {
              if (advanceTimer.current) clearTimeout(advanceTimer.current);
              setStepIndex(Math.max(0, safeIndex - 1));
            }}
            className="h-11 px-4 text-base"
          >
            <ArrowLeft aria-hidden="true" className="size-4" />
            Back
          </Button>

          {current.kind === "choice" && !isLastStep ? (
            <span className="text-sm text-muted-foreground">
              Pick an answer to continue — nothing is saved to an account yet.
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
