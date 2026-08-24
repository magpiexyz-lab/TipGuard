"use client";

import { useState, useEffect } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Menu } from "lucide-react";
import { createClient } from "@/lib/supabase";
import { Button, buttonVariants } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import type { AuthChangeEvent, Session, User } from "@supabase/supabase-js";

/**
 * Routes that render their own navigation, or where app chrome is wrong.
 *
 * `/sign` is the important one: the person on that page is a restaurant
 * EMPLOYEE holding a tokenized link. They have no TipGuard account and never
 * will. Showing them "Dashboard" and "Log out" invites a dead end at best and
 * suggests the notice is something they must sign up for at worst.
 *
 * Landing and variant routes carry their own in-page marketing nav; mounting
 * the global bar on top of them doubles the brand mark and stacks two navs
 * above the fold (framework/nextjs.md, fix #1072).
 */
// Always chromeless: landing owns its own SiteHeader, and the auth screens
// should not advertise the app they are gating.
const CHROMELESS_EXACT = ["/", "/login", "/signup"];
// Chromeless only for signed-out visitors. /sign is reached two ways: an
// employee opening an emailed token link (no account -- app links would be dead
// ends, so stay chromeless), or an owner clicking "Sign a notice" in this very
// nav. Suppressing it unconditionally stranded that owner with no way back.
const CHROMELESS_WHEN_SIGNED_OUT = ["/sign"];
const CHROMELESS_PREFIXES = ["/v/", "/auth/"];

// DELIBERATE DEVIATION from the derive_scope_pages emission (wire.md Step
// 5b.3). That derivation lists every scope page except landing/login/signup and
// /auth/*, which is a page inventory, not a menu: it has no notion of WHO a page
// is for. Emitting it verbatim produced eight links, and one of them was a dead
// end -- /sign is the employee surface, reachable only with an emailed token, so
// an owner clicking "Sign a notice" landed on "This signing link is incomplete".
//
// Two audiences, two menus:
const PUBLIC_LINKS = [
  { href: "/score", label: "Readiness score" },
  { href: "/pricing", label: "Pricing" },
];

// Signed-in owners get the pages they actually work in, in workflow order
// rather than the derivation's golden-path-then-alphabetical ordering (which
// put Audit file ahead of Dashboard).
//
// Not here on purpose:
//   /score   - the anonymous acquisition hook. Once an account exists the score
//              lives on the dashboard; re-taking it overwrites nothing useful.
//   /pricing - reachable from the dashboard upgrade CTA, which b-10 requires on
//              every account, plus the landing page and the footer. checkout_started
//              (h-06) is still measurable from those.
//   /sign    - employee-only, see above.
const OWNER_LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/staff", label: "Staff" },
  { href: "/notices", label: "Notices" },
  { href: "/violations", label: "Findings" },
  { href: "/audit-file", label: "Audit file" },
];

export function NavBar() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    const supabase = createClient();

    supabase.auth
      .getSession()
      .then(({ data: { session } }: { data: { session: Session | null } }) => {
        setUser(session?.user ?? null);
        setLoading(false);
      });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(
      (_event: AuthChangeEvent, session: Session | null) => {
        setUser(session?.user ?? null);
      }
    );

    return () => subscription.unsubscribe();
  }, []);

  async function handleLogout() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/");
    router.refresh();
  }

  const path = pathname ?? "";
  // While auth is still resolving, treat the visitor as signed out. That is the
  // safe default: an employee never sees a flash of owner navigation, and the
  // owner gets the nav a beat later rather than never.
  const signedIn = !loading && user !== null;
  const suppressed =
    CHROMELESS_EXACT.includes(path) ||
    CHROMELESS_PREFIXES.some((prefix) => path.startsWith(prefix)) ||
    (!signedIn && CHROMELESS_WHEN_SIGNED_OUT.includes(path));
  if (suppressed) return null;

  const navLinks = (
    <>
      {/* DERIVED-FROM: derive_scope_pages (deliberately narrowed — see the
          PUBLIC_LINKS / OWNER_LINKS note above before widening this back to the
          raw derive_scope_pages emission from wire.md Step 5b.3). */}
      {(signedIn ? OWNER_LINKS : PUBLIC_LINKS).map((link) => (
        <Link
          key={link.href}
          href={link.href}
          onClick={() => setOpen(false)}
          className="text-sm font-medium text-muted-foreground transition-colors duration-[140ms] hover:text-foreground"
        >
          {link.label}
        </Link>
      ))}
    </>
  );

  const authSection = loading ? (
    <Button variant="outline" disabled className="min-w-[70px]">
      &nbsp;
    </Button>
  ) : user ? (
    <>
      <span className="max-w-[200px] truncate text-sm text-muted-foreground">
        {user.email}
      </span>
      <Button variant="outline" onClick={handleLogout}>
        Log out
      </Button>
    </>
  ) : (
    <Link href="/login" className={buttonVariants({ variant: "outline" })}>
      Log in
    </Link>
  );

  return (
    // Sticky, not fixed: fixed would need a matching body offset on every page
    // and silently overlap the first section wherever one was missed.
    // `bg-background` is opaque, so content does not show through on scroll.
    <nav
      aria-label="Primary"
      className="sticky top-0 z-40 flex items-center justify-between border-b border-border bg-background px-6 py-4"
    >
      <Link href="/" className="flex items-center gap-2">
        {/* Decorative: the brand name is announced by the adjacent <span>.
            unoptimized: next/image rejects SVG by default (HTTP 400). */}
        <Image src="/images/logo.svg" alt="" aria-hidden width={32} height={32} unoptimized />
        <span className="font-display text-xl tracking-[-0.8px] [word-spacing:0.06em]">TipGuard</span>
      </Link>

      {/* Desktop nav */}
      <div className="hidden items-center gap-4 md:flex">
        {navLinks}
        {authSection}
      </div>

      {/* Mobile hamburger menu. SheetTrigger renders its own <button> — do NOT
          wrap a <Button> inside it (nested buttons hydrate-error, fix #1068). */}
      <div className="md:hidden">
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger
            aria-label="Open menu"
            className={buttonVariants({ variant: "ghost", size: "icon" })}
          >
            <Menu className="h-5 w-5" />
          </SheetTrigger>
          <SheetContent side="right" className="w-[280px]">
            {/* WCAG 4.1.2: every dialog needs an accessible name. */}
            <SheetTitle className="sr-only">Site navigation</SheetTitle>
            <div className="mt-8 flex flex-col gap-4 px-4">
              {navLinks}
              {authSection}
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </nav>
  );
}
