import type { Metadata } from "next";
import { LegalPage, Section } from "../legal/legal-layout";

export const metadata: Metadata = {
  title: "Privacy · TipGuard",
  description:
    "What TipGuard collects, why, who processes it, and how to have it deleted.",
};

/**
 * `/privacy` — required by Google's OAuth consent screen before the app can be
 * published, and independently required of any product that asks a restaurant
 * to upload its payroll roster.
 *
 * Written from the actual schema (supabase/migrations/) and the actual
 * sub-processors, not from a template. If a data flow changes, this page is
 * part of the change.
 */
export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      updated="20 August 2026"
      intro="TipGuard helps restaurant operators produce and retain tip-credit notices. That means we hold payroll-adjacent records about people who are not our users — your employees — so this page states plainly what we keep, why we keep it, and how to get rid of it."
    >
      <Section heading="Who we are">
        <p>
          TipGuard is operated by Draft Labs. Contact:{" "}
          <a href="mailto:privacy@draftlabs.org" className="underline underline-offset-4">
            privacy@draftlabs.org
          </a>
          .
        </p>
        <p>
          TipGuard is an early-stage product under active evaluation. It is not a
          law firm and nothing it produces is legal advice.
        </p>
      </Section>

      <Section heading="What we collect from account holders">
        <p>
          When you create an account we store your email address and, if you use
          Google sign-in, the name and email Google returns. Passwords are
          handled by our authentication provider and are never stored in a form
          we can read.
        </p>
        <p>
          We also store what you enter in the product: your restaurant name, home
          state, audit-readiness questionnaire answers and the resulting score
          and gap list.
        </p>
      </Section>

      <Section heading="What we collect about your employees">
        <p>
          This is the part that matters most, so it is stated in full. When you
          import a roster we store, for each employee: name, email address, job
          role, hire date, hourly rate, home state, and whether they participate
          in a tip pool.
        </p>
        <p>
          When an employee signs a notice we additionally record the name they
          typed, the timestamp, a frozen copy of the exact notice text they
          agreed to, and — because a signature record is worthless as evidence
          without them — the IP address and browser user-agent of the device used
          to sign.
        </p>
        <p>
          You are the controller of that employee data; we process it on your
          instructions. Telling your staff that this record exists is your
          responsibility, and in most cases it is also a legal one.
        </p>
      </Section>

      <Section heading="Signature records cannot be edited or deleted individually">
        <p>
          The signature vault is append-only by design, enforced at the database
          level. A compliance record that could be quietly altered after the fact
          would be useless to you in an audit, so we made it impossible — for you
          and for us. Signature rows are removed only when the account that owns
          them is deleted, and then all of them go together.
        </p>
      </Section>

      <Section heading="Analytics">
        <p>
          We use PostHog to understand how the product is used — which pages are
          viewed, which actions are taken, and where people abandon a flow. This
          is how an early-stage product learns whether it is worth continuing.
        </p>
        <p>
          Analytics events carry a random identifier, not your name. URLs that
          contain a signing token are stripped before any event leaves the
          browser, so a link that would let someone sign on an employee&rsquo;s
          behalf never reaches our analytics.
        </p>
      </Section>

      <Section heading="Who else processes this data">
        <p>
          We use a small number of sub-processors, each for one job: Supabase
          (database and authentication), Vercel (hosting), Resend (sending
          notice and account email), PostHog (product analytics), and Anthropic
          (generating plain-English explanations of compliance findings).
        </p>
        <p>
          Compliance scoring, violation detection and the audit file are
          deterministic — they are computed in our own code and are never sent to
          a model.
        </p>
        <p>
          We do not sell personal data, and we do not share it for advertising.
        </p>
      </Section>

      <Section heading="Where data is held and for how long">
        <p>
          Data is stored in the United States. We keep it for as long as your
          account exists. Delete your account and the associated records —
          employees, notices, signatures, findings — are deleted with it.
        </p>
      </Section>

      <Section heading="Your rights">
        <p>
          You can ask us for a copy of your data, ask us to correct it, or ask us
          to delete it, by emailing{" "}
          <a href="mailto:privacy@draftlabs.org" className="underline underline-offset-4">
            privacy@draftlabs.org
          </a>
          . Depending on where you live you may have additional rights under laws
          such as the GDPR or the CCPA; we will honour those requests regardless
          of where you are.
        </p>
        <p>
          If you are an employee of a TipGuard customer and want your record
          amended or removed, contact your employer first — it is their record.
          If that fails, write to us and we will help.
        </p>
      </Section>

      <Section heading="Changes">
        <p>
          If we change how data is handled, we will update this page and its
          date. Material changes will be notified to account holders by email.
        </p>
      </Section>
    </LegalPage>
  );
}
