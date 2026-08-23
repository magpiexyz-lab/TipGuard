"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";

import type { AuthChangeEvent, Session } from "@supabase/supabase-js";

import { createClient } from "@/lib/supabase";
import { cn } from "@/lib/utils";

/**
 * Minimal brand bar for the pages NavBar deliberately suppresses
 * (CHROMELESS_EXACT / CHROMELESS_PREFIXES in src/components/nav-bar.tsx):
 * /sign, /login, /signup and /auth/*.
 *
 * Those pages are chromeless for good reasons - an employee opening a signing
 * link has no TipGuard account, so "Staff", "Notices" and "Dashboard" would be
 * dead ends, and an auth screen should not advertise the app it is gating. But
 * suppressing the whole NavBar also left them with no route back to the
 * marketing site at all, which is a dead end of its own: the signer cannot find
 * out what TipGuard is, and an owner who lands on /login by mistake is stuck.
 *
 * So this is a brand mark, not navigation: one link, to the landing page.
 */
export function BrandHeader({
  tone = "paper",
  className,
  hideWhenSignedIn = false,
}: {
  /** `ink` for dark surfaces, `paper` for light ones. */
  tone?: "paper" | "ink";
  className?: string;
  /**
   * Set on /sign. NavBar suppresses itself there only for signed-out visitors,
   * so once an owner is authenticated the full nav returns and this mark would
   * be a second TipGuard wordmark stacked under the first.
   */
  hideWhenSignedIn?: boolean;
}) {
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    if (!hideWhenSignedIn) return;
    const supabase = createClient();
    supabase.auth
      .getUser()
      .then((res: { data: { user: unknown | null } }) => setSignedIn(res.data.user !== null))
      .catch(() => setSignedIn(false));
    const { data } = supabase.auth.onAuthStateChange(
      (_event: AuthChangeEvent, session: Session | null) =>
        setSignedIn(session?.user != null),
    );
    return () => data.subscription.unsubscribe();
  }, [hideWhenSignedIn]);

  if (hideWhenSignedIn && signedIn) return null;

  return (
    <div className={cn("flex items-center", className)}>
      <Link
        href="/"
        className={cn(
          "-mx-1 inline-flex min-h-11 items-center gap-2 rounded-sm px-1",
          "transition-opacity duration-[var(--duration-fast)] hover:opacity-80",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brass",
        )}
      >
        {/* Decorative: the brand name is announced by the adjacent <span>.
            unoptimized: next/image rejects SVG by default (HTTP 400). */}
        <Image
          src="/images/logo.svg"
          alt=""
          aria-hidden
          width={26}
          height={26}
          unoptimized
        />
        <span
          className={cn(
            "font-display text-lg tracking-[-0.6px]",
            tone === "ink" ? "text-[#ECE8DA]" : "text-foreground",
          )}
        >
          TipGuard
        </span>
      </Link>
    </div>
  );
}
