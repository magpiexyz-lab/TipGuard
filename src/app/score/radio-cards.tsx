"use client";

// WAI-ARIA radiogroup implemented over rich option cards.
//
// A native <input type="radio"> gets the keyboard contract for free; a custom
// button cluster does not. This component implements it explicitly: one
// tabIndex=0 per group (roving tabindex), Arrow/Home/End move focus AND
// selection, and the container carries role="radiogroup" + an accessible name.
// See .claude/stacks/ui/shadcn.md "custom role=radio clusters".

import { type KeyboardEvent } from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ChoiceOption } from "./questions";

function handleRadioGroupKey(
  event: KeyboardEvent<HTMLElement>,
  values: readonly string[],
  current: string | null,
  onChange: (value: string) => void,
): void {
  const last = values.length - 1;
  if (last < 0) return;
  const currentIdx = current === null ? 0 : Math.max(0, values.indexOf(current));
  // No initial value: every reachable branch below either assigns or returns,
  // so an initializer would be dead (@typescript-eslint/no-useless-assignment).
  let nextIdx: number;
  switch (event.key) {
    case "ArrowRight":
    case "ArrowDown":
      nextIdx = currentIdx === last ? 0 : currentIdx + 1;
      break;
    case "ArrowLeft":
    case "ArrowUp":
      nextIdx = currentIdx === 0 ? last : currentIdx - 1;
      break;
    case "Home":
      nextIdx = 0;
      break;
    case "End":
      nextIdx = last;
      break;
    default:
      return;
  }
  event.preventDefault();
  onChange(values[nextIdx]);
  const container = (event.currentTarget as HTMLElement).parentElement;
  (container?.children[nextIdx] as HTMLElement | undefined)?.focus();
}

function rovingTabIndex(values: readonly string[], current: string | null, index: number): 0 | -1 {
  if (current === null) return index === 0 ? 0 : -1;
  return values[index] === current ? 0 : -1;
}

export function RadioCards({
  options,
  value,
  onChange,
  ariaLabel,
  columns = 1,
}: {
  options: ChoiceOption[];
  value: string | null;
  onChange: (value: string) => void;
  ariaLabel: string;
  columns?: 1 | 2 | 3;
}) {
  const values = options.map((option) => option.value);

  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cn(
        "grid gap-2",
        columns >= 2 && "sm:grid-cols-2",
        columns === 3 && "lg:grid-cols-3",
      )}
    >
      {options.map((option, index) => {
        const selected = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={rovingTabIndex(values, value, index)}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => handleRadioGroupKey(event, values, value, onChange)}
            className={cn(
              "group/option relative flex min-h-11 w-full cursor-pointer items-start gap-2.5 rounded-lg bg-card px-3 py-2.5 text-left",
              "ring-1 ring-foreground/10 outline-none",
              "transition-[box-shadow,transform,background-color] duration-[var(--duration-fast)] ease-[var(--ease-stamp)]",
              "hover:-translate-y-0.5 hover:shadow-[var(--shadow-ledger-2)]",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brass",
              selected
                ? "bg-brass-soft/45 ring-2 ring-brass shadow-[var(--shadow-ledger-1)] dark:bg-brass/12"
                : "hover:bg-card",
            )}
          >
            {/* Stamp mark: the pressed seal on the chosen answer. */}
            <span
              aria-hidden="true"
              className={cn(
                "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-sm",
                "transition-all duration-[var(--duration-base)] ease-[var(--ease-stamp)]",
                selected
                  ? "scale-100 bg-brass text-ink"
                  : "scale-95 bg-transparent ring-1 ring-foreground/25",
              )}
            >
              <Check
                className={cn(
                  "size-3.5 transition-opacity duration-[var(--duration-base)]",
                  selected ? "opacity-100" : "opacity-0",
                )}
              />
            </span>

            <span className="min-w-0 flex-1">
              <span className="block text-base font-medium leading-snug text-foreground">
                {option.label}
              </span>
              <span className="mt-1 block text-sm leading-relaxed text-muted-foreground">
                {option.detail}
              </span>
            </span>

            {option.hint ? (
              <span className="figure shrink-0 self-center text-sm text-muted-foreground">
                {option.hint}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
