-- TipGuard initial schema (bootstrap / scaffold-wire).
--
-- Tenancy model: `accounts` is the tenant root. Every other table carries
-- `account_id` and inherits its RLS scope from `accounts.user_id = auth.uid()`.
--
-- Write model: EVERY mutation in this product goes through an API route that
-- uses the service-role client (`createServiceRoleClient()`), because every
-- table below carries either a state machine (`notices.status`,
-- `violations.status`), a billing column (`accounts.plan`,
-- `accounts.current_period_end`), or a legal record (`signatures`). Per
-- `.claude/stacks/database/supabase.md` "When a table holds state-machine
-- financial state, write policies must be service-role-only", clients get
-- SELECT policies only. The ABSENCE of INSERT/UPDATE/DELETE policies is what
-- makes PostgREST reject a browser-console `supabase.from('notices').update(...)`
-- — application-layer filters are not the boundary, the missing policy is.
--
-- Idempotent by construction: CREATE TABLE IF NOT EXISTS + DROP POLICY IF
-- EXISTS ... CREATE POLICY, so both `supabase db push` and the Vercel
-- `prebuild` auto-migrate runner can apply this file repeatedly.

-- ---------------------------------------------------------------------------
-- accounts — tenant root: one row per restaurant/owner.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL UNIQUE,
  restaurant_name text NOT NULL DEFAULT '',
  home_state text NOT NULL DEFAULT '',
  -- Billing state. Written ONLY by the Stripe webhook (service role).
  plan text NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'shield')),
  stripe_customer_id text,
  current_period_end timestamptz,
  -- Anonymous /score questionnaire result, attached at signup (b-03).
  readiness_score integer CHECK (readiness_score IS NULL OR (readiness_score >= 0 AND readiness_score <= 100)),
  gap_list jsonb,
  scored_at timestamptz,
  -- Set by POST /api/violations/scan. Distinguishes "never scanned" from
  -- "scanned and genuinely clean" — without it a first clean scan is
  -- indistinguishable from no scan at all.
  last_scan_at timestamptz,
  created_at timestamptz DEFAULT now()
);

COMMENT ON TABLE accounts IS 'Tenant root. One row per restaurant owner; every other table scopes to accounts.id.';
COMMENT ON COLUMN accounts.last_scan_at IS 'Timestamp of the last compliance scan. NULL means never scanned (distinct from scanned-and-clean).';

ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "accounts_select_own" ON accounts;
CREATE POLICY "accounts_select_own" ON accounts
  FOR SELECT USING (auth.uid() = user_id);

-- No INSERT / UPDATE / DELETE policies for clients: plan, stripe_customer_id,
-- current_period_end, readiness_score and last_scan_at are all server-managed.
-- POST /api/account/score and the Stripe webhook write via the service role.

-- Resolves the caller's account id once, for use in every child-table policy.
-- SECURITY INVOKER (the default) so it evaluates under the caller's RLS.
CREATE OR REPLACE FUNCTION public.current_account_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT id FROM accounts WHERE user_id = auth.uid()
$$;

-- ---------------------------------------------------------------------------
-- employees — tipped staff imported from the roster CSV (b-04).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS employees (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  account_id uuid REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
  name text NOT NULL,
  email text NOT NULL,
  role text NOT NULL,
  hire_date date NOT NULL,
  hourly_rate numeric(10, 2) NOT NULL,
  state text NOT NULL,
  -- Input to the ineligible-tip-pool rule class (b-08).
  in_tip_pool boolean NOT NULL DEFAULT true,
  created_at timestamptz DEFAULT now(),
  UNIQUE (account_id, email)
);

COMMENT ON TABLE employees IS 'Tipped staff roster. One notice and one set of pay periods hang off each row.';

ALTER TABLE employees ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "employees_select_own" ON employees;
CREATE POLICY "employees_select_own" ON employees
  FOR SELECT USING (account_id = public.current_account_id());

-- ---------------------------------------------------------------------------
-- pay_periods — per-employee workweek data. The input to the overtime-basis
-- and sub-minimum-shortfall rule classes; without it b-08 can only run the
-- missing-notice rule.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pay_periods (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  account_id uuid REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
  employee_id uuid REFERENCES employees(id) ON DELETE CASCADE NOT NULL,
  period_start date NOT NULL,
  period_end date NOT NULL,
  hours_worked numeric(10, 2) NOT NULL DEFAULT 0,
  overtime_hours numeric(10, 2) NOT NULL DEFAULT 0,
  overtime_rate_used numeric(10, 2),
  tips_reported numeric(12, 2) NOT NULL DEFAULT 0,
  cash_wage_paid numeric(10, 2) NOT NULL DEFAULT 0,
  created_at timestamptz DEFAULT now()
);

COMMENT ON TABLE pay_periods IS 'Workweek hours/tips/wage inputs for the compliance scan (b-08).';

ALTER TABLE pay_periods ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "pay_periods_select_own" ON pay_periods;
CREATE POLICY "pay_periods_select_own" ON pay_periods
  FOR SELECT USING (account_id = public.current_account_id());

CREATE INDEX IF NOT EXISTS pay_periods_employee_idx ON pay_periods (employee_id);

-- ---------------------------------------------------------------------------
-- notices — one state-specific tip-credit notice per employee (b-05).
-- `status` is a state machine: draft -> sent -> signed. Guarded in the API
-- routes with a 409 on an out-of-order transition.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notices (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  account_id uuid REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
  employee_id uuid REFERENCES employees(id) ON DELETE CASCADE NOT NULL,
  state text NOT NULL,
  rule_version text NOT NULL,
  cash_wage_paid numeric(10, 2) NOT NULL,
  tip_credit_claimed boolean NOT NULL,
  notice_text text NOT NULL,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sent', 'signed')),
  sent_at timestamptz,
  created_at timestamptz DEFAULT now(),
  UNIQUE (employee_id, rule_version)
);

COMMENT ON TABLE notices IS 'Rendered per-employee tip-credit notices. status is a draft->sent->signed state machine.';
COMMENT ON COLUMN notices.notice_text IS 'The rendered notice INCLUDING the counsel-review disclaimer. Frozen into signatures.notice_text_snapshot at signature time.';

ALTER TABLE notices ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "notices_select_own" ON notices;
CREATE POLICY "notices_select_own" ON notices
  FOR SELECT USING (account_id = public.current_account_id());

CREATE INDEX IF NOT EXISTS notices_account_idx ON notices (account_id);

-- ---------------------------------------------------------------------------
-- signing_tokens — single-use tokenized signing links (b-06 -> b-07).
--
-- NO client policies at all, not even SELECT. The signer has no session, so
-- the /sign page and POST /api/notices/sign resolve tokens with the service
-- role. Only the SHA-256 digest is stored: a database leak does not hand an
-- attacker a set of working signing links.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signing_tokens (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  account_id uuid REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
  notice_id uuid REFERENCES notices(id) ON DELETE CASCADE NOT NULL,
  token_hash text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  created_at timestamptz DEFAULT now()
);

COMMENT ON TABLE signing_tokens IS 'SHA-256 digests of single-use signing links. No RLS policy exists — service role only.';

ALTER TABLE signing_tokens ENABLE ROW LEVEL SECURITY;
-- Intentionally no policies. RLS-enabled + zero policies = deny all for
-- anon/authenticated; the service-role client bypasses RLS entirely.

CREATE INDEX IF NOT EXISTS signing_tokens_notice_idx ON signing_tokens (notice_id);

-- ---------------------------------------------------------------------------
-- signatures — the immutable acknowledgment vault (b-07).
--
-- Immutability is enforced by the DATABASE, not by the API:
--   1. No UPDATE and no DELETE policy exists, so PostgREST rejects every
--      client-issued mutation.
--   2. A BEFORE UPDATE OR DELETE trigger raises, so even a compromised
--      service-role key cannot rewrite a signed record.
--   3. `notice_text_snapshot` is a COPY of the notice text, not a reference,
--      so later edits to `notices` cannot alter what was legally acknowledged.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signatures (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  account_id uuid REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
  notice_id uuid REFERENCES notices(id) ON DELETE CASCADE NOT NULL,
  signer_name text NOT NULL,
  signed_at timestamptz NOT NULL DEFAULT now(),
  ip_address text NOT NULL DEFAULT '',
  user_agent text NOT NULL DEFAULT '',
  notice_text_snapshot text NOT NULL,
  created_at timestamptz DEFAULT now()
);

COMMENT ON TABLE signatures IS 'Append-only vault. INSERT is service-role only; UPDATE/DELETE are blocked by policy absence AND by trigger.';

ALTER TABLE signatures ENABLE ROW LEVEL SECURITY;

-- The owner may READ their own signature records (the audit file is built
-- from them). There is deliberately NO UPDATE and NO DELETE policy.
DROP POLICY IF EXISTS "signatures_select_own" ON signatures;
CREATE POLICY "signatures_select_own" ON signatures
  FOR SELECT USING (account_id = public.current_account_id());

CREATE OR REPLACE FUNCTION public.signatures_are_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'signatures are immutable: % is not permitted', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS signatures_no_update ON signatures;
CREATE TRIGGER signatures_no_update
  BEFORE UPDATE OR DELETE ON signatures
  FOR EACH ROW EXECUTE FUNCTION public.signatures_are_immutable();

CREATE INDEX IF NOT EXISTS signatures_notice_idx ON signatures (notice_id);

-- ---------------------------------------------------------------------------
-- violations — compliance-scan findings (b-08 / b-09).
-- `status` is a state machine: open -> resolved. Resolving flips the status;
-- the row is never deleted, so the audit record survives the fix.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS violations (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  account_id uuid REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
  employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
  rule_class text NOT NULL CHECK (
    rule_class IN ('overtime_base', 'ineligible_tip_pool', 'subminimum_shortfall', 'missing_notice')
  ),
  severity text NOT NULL CHECK (severity IN ('critical', 'high', 'medium')),
  estimated_exposure_usd numeric(12, 2) NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
  detail text NOT NULL DEFAULT '',
  detected_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  created_at timestamptz DEFAULT now()
);

COMMENT ON TABLE violations IS 'Findings from the compliance scan. Resolving flips status; rows are never deleted (audit record).';

ALTER TABLE violations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "violations_select_own" ON violations;
CREATE POLICY "violations_select_own" ON violations
  FOR SELECT USING (account_id = public.current_account_id());

CREATE INDEX IF NOT EXISTS violations_account_status_idx ON violations (account_id, status);

-- ---------------------------------------------------------------------------
-- fake_door_clicks — durable mirror of the "Connect Gusto / Toast" intent
-- signal (b-04). The primary signal is the `payroll_connect_clicked`
-- analytics event; this table exists so demand can be counted per account
-- without a PostHog query. No PII is recorded — provider only.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fake_door_clicks (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  account_id uuid REFERENCES accounts(id) ON DELETE CASCADE,
  provider text NOT NULL,
  created_at timestamptz DEFAULT now()
);

COMMENT ON TABLE fake_door_clicks IS 'Payroll-integration intent signal. Provider only — never an email or any other PII.';

ALTER TABLE fake_door_clicks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "fake_door_clicks_select_own" ON fake_door_clicks;
CREATE POLICY "fake_door_clicks_select_own" ON fake_door_clicks
  FOR SELECT USING (account_id = public.current_account_id());

-- ---------------------------------------------------------------------------
-- feedback — post-activation feedback widget submissions.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feedback (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  account_id uuid REFERENCES accounts(id) ON DELETE CASCADE,
  source text,
  feedback text,
  activation_action text NOT NULL,
  created_at timestamptz DEFAULT now()
);

COMMENT ON TABLE feedback IS 'Post-activation feedback. Written by POST /api/feedback (service role) after a session check.';

ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "feedback_select_own" ON feedback;
CREATE POLICY "feedback_select_own" ON feedback
  FOR SELECT USING (account_id = public.current_account_id());

-- ---------------------------------------------------------------------------
-- stripe_events — webhook idempotency ledger (b-11).
-- The PRIMARY KEY is what makes the INSERT + catch-23505 pattern atomic:
-- two concurrent deliveries of the same event id produce exactly one insert.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stripe_events (
  stripe_event_id text PRIMARY KEY,
  received_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE stripe_events IS 'Stripe webhook replay guard. Service role only.';

ALTER TABLE stripe_events ENABLE ROW LEVEL SECURITY;
-- No policies: only the webhook handler (service role) touches this table.

-- ---------------------------------------------------------------------------
-- Column-level defense-in-depth. Even if a future migration adds an UPDATE
-- policy to `accounts`, PostgREST honours column privileges and rejects any
-- PATCH from a user JWT that touches a server-managed column.
-- ---------------------------------------------------------------------------
REVOKE UPDATE (plan, stripe_customer_id, current_period_end, readiness_score, gap_list, last_scan_at)
  ON accounts FROM authenticated;
