import type { Metadata } from "next";
import { LegalPage, Section } from "../legal/legal-layout";

export const metadata: Metadata = {
  title: "Terms · TipGuard",
  description:
    "The terms you accept by using TipGuard, including the limits of what it is.",
};

/**
 * `/terms` — required alongside /privacy by Google's OAuth consent screen.
 *
 * The substantive point of this document is the disclaimer: TipGuard produces
 * compliance paperwork from a per-state rule library, and a customer who reads
 * that as legal advice is a customer who will be surprised in an audit. That
 * warning already appears on the notice itself; it belongs here too.
 */
export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of Service"
      updated="20 August 2026"
      intro="These terms cover your use of TipGuard. The most important one is the third section, so if you read nothing else, read that."
    >
      <Section heading="Agreement">
        <p>
          By creating an account or using TipGuard you agree to these terms. If
          you are accepting on behalf of a business, you confirm you are
          authorised to bind it.
        </p>
      </Section>

      <Section heading="What TipGuard does">
        <p>
          TipGuard generates state-specific tip-credit notices, collects
          employee acknowledgments, flags likely compliance gaps, and assembles a
          dated audit file from those records.
        </p>
      </Section>

      <Section heading="TipGuard is not legal advice">
        <p>
          This is the part that matters. TipGuard is software, not a law firm.
          The notices it generates come from a per-state rule library maintained
          on a best-effort basis. Wage-and-hour law changes, varies by
          jurisdiction, and turns on facts we cannot see.
        </p>
        <p>
          Nothing TipGuard produces is legal advice, and no attorney-client
          relationship is created by using it. Have your counsel review notices
          before you distribute them to staff. A generated notice does not
          guarantee compliance and will not, on its own, defend a claim.
        </p>
        <p>
          Exposure figures shown in the product are illustrative arithmetic based
          on the inputs you provide. They are not a prediction of what any
          agency, court or plaintiff would actually assess.
        </p>
      </Section>

      <Section heading="Your responsibilities">
        <p>
          You are responsible for the accuracy of what you enter — rosters, pay
          rates, hire dates and states. TipGuard&rsquo;s output is only as
          correct as its input.
        </p>
        <p>
          You are responsible for having a lawful basis to upload your
          employees&rsquo; details and for telling them their acknowledgments are
          recorded. You must not use TipGuard to send notices to people who are
          not your employees.
        </p>
        <p>
          Keep your credentials to yourself. Activity under your account is
          treated as yours.
        </p>
      </Section>

      <Section heading="Availability and current status">
        <p>
          TipGuard is an early-stage product being actively evaluated. Features
          may change or be withdrawn, and the service is provided without any
          uptime commitment. Export your audit file if you need a copy you
          control.
        </p>
        <p>
          TipGuard Shield is announced but not yet available for purchase.
          Joining the waitlist costs nothing, charges nothing, and is not an
          order or a contract.
        </p>
      </Section>

      <Section heading="Liability">
        <p>
          TipGuard is provided &ldquo;as is&rdquo;, without warranties of any
          kind to the extent the law allows. We are not liable for indirect or
          consequential losses, including fines, back-pay assessments, penalties
          or legal costs arising from your compliance position.
        </p>
        <p>
          Nothing here limits liability that cannot lawfully be limited.
        </p>
      </Section>

      <Section heading="Ending your use">
        <p>
          You can stop using TipGuard and request deletion at any time. We may
          suspend an account that is being used unlawfully or in a way that
          endangers other customers&rsquo; data.
        </p>
      </Section>

      <Section heading="Changes">
        <p>
          We may update these terms. The date at the top reflects the current
          version, and material changes will be notified to account holders by
          email.
        </p>
      </Section>
    </LegalPage>
  );
}
