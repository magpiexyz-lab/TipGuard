-- ---------------------------------------------------------------------------
-- 002 — Shield waitlist replaces the Stripe checkout path (b-10 / b-11).
--
-- The MVP measures intent to pay, not payment. h-06 is scored on
-- `checkout_started / notice_sent`, which fires on the upgrade click and never
-- depended on a completed charge. The fake door captures the follow-through:
-- who, having clicked, will also leave an address to be told when it opens.
--
-- `accounts.plan` / `stripe_customer_id` / `current_period_end` are left in
-- place. They are server-managed, already REVOKEd from `authenticated`, and
-- every account simply stays 'free'. Dropping them would churn the tenant root
-- and its column grants for no behavioural gain.
-- ---------------------------------------------------------------------------

-- The replay guard existed only to make Stripe webhook delivery idempotent.
-- With no webhook, it has no writer.
DROP TABLE IF EXISTS stripe_events;

CREATE TABLE IF NOT EXISTS waitlist (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  email text NOT NULL,
  -- Context at the moment of joining, so the list reads back as a qualified
  -- pipeline rather than a bare set of addresses.
  notices_sent_at_join integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  -- One expression of interest per account. A second confirm is an upsert, not
  -- a duplicate row, so the table stays a count of *owners*, not of clicks.
  UNIQUE (account_id)
);

COMMENT ON TABLE waitlist IS 'Shield fake-door signups (b-11). One row per account; UNIQUE(account_id) keeps it a count of owners, not clicks.';
COMMENT ON COLUMN waitlist.notices_sent_at_join IS 'Notices the owner had already sent when they joined — separates idle curiosity from active need.';

ALTER TABLE waitlist ENABLE ROW LEVEL SECURITY;

-- An owner may read back their own entry so the panel can render "you are on
-- the list" on a return visit. Writes go through POST /api/waitlist under the
-- service role, which stamps account_id from the verified session — never from
-- anything the client sent.
DROP POLICY IF EXISTS "waitlist_select_own" ON waitlist;
CREATE POLICY "waitlist_select_own" ON waitlist
  FOR SELECT USING (account_id = public.current_account_id());

-- No client INSERT / UPDATE / DELETE policy: account_id and
-- notices_sent_at_join are server-derived, and a client-writable waitlist is a
-- client-writable claim about which account expressed intent.

CREATE INDEX IF NOT EXISTS waitlist_created_at_idx ON waitlist (created_at DESC);
