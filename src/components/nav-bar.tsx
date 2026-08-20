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
const CHROMELESS_EXACT = ["/", "/sign", "/login", "/signup"];
const CHROMELESS_PREFIXES = ["/v/", "/auth/"];

const NAV_LINKS = [
  // Golden-path pages first, in funnel sequence.
  { href: "/score", label: "Readiness score" },
  { href: "/staff", label: "Staff" },
  { href: "/notices", label: "Notices" },
  // Behavior-only pages, alphabetical.
  { href: "/audit-file", label: "Audit file" },
  { href: "/dashboard", label: "Dashboard" },
  { href: "/pricing", label: "Pricing" },
  { href: "/sign", label: "Sign a notice" },
  { href: "/violations", label: "Findings" },
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

  const suppressed =
    CHROMELESS_EXACT.includes(pathname ?? "") ||
    CHROMELESS_PREFIXES.some((prefix) => (pathname ?? "").startsWith(prefix));
  if (suppressed) return null;

  const navLinks = (
    <>
      {/* DERIVED-FROM: derive_scope_pages */}
      {/* Emitted from `derive_scope_pages(experiment)` — the canonical SET
          inventory, NOT the golden_path sequence. Excludes landing, login,
          signup and the /auth/* routes. Ordering: golden_path pages first in
          funnel sequence, behavior-only pages appended alphabetically.
          See .claude/procedures/wire.md Step 5b.3. */}
      {NAV_LINKS.map((link) => (
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
        <span className="font-display text-xl tracking-[-0.8px]">TipGuard</span>
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
