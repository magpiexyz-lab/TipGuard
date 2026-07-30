#!/usr/bin/env bash
# verify-local.sh — One-command local verification for bootstrapped projects.
# Installs deps, starts services, generates .env.local, runs tests, cleans up.
#
# Usage: bash scripts/verify-local.sh   (or: make verify-local)

set -euo pipefail

# --- Colors & helpers --------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

step()  { echo -e "\n${BOLD}[$1/4] $2${NC}"; }
ok()    { echo -e "  ${GREEN}✓${NC} $1"; }
warn()  { echo -e "  ${YELLOW}!${NC} $1"; }
fail()  { echo -e "  ${RED}✗${NC} $1"; }

# --- Stack detection ---------------------------------------------------------

HAS_SUPABASE=false
HAS_PLAYWRIGHT=false
HAS_ENV_EXAMPLE=false

[ -f supabase/config.toml ] && HAS_SUPABASE=true
[ -f playwright.config.ts ] && HAS_PLAYWRIGHT=true
[ -f .env.example ]         && HAS_ENV_EXAMPLE=true

# --- Cleanup on exit --------------------------------------------------------

SUPABASE_STARTED=false

cleanup() {
  if [ "$SUPABASE_STARTED" = true ]; then
    echo ""
    echo -e "${BOLD}Cleaning up...${NC}"
    npx supabase stop >/dev/null 2>&1 || true
    ok "Local Supabase stopped"
  fi
}
trap cleanup EXIT

# --- Pre-flight checks -------------------------------------------------------

if [ ! -f package.json ]; then
  fail "No package.json found. Run /bootstrap first."
  exit 1
fi

# --- Step 1: Install dependencies -------------------------------------------

step 1 "Installing dependencies..."
npm install --prefer-offline 2>&1 | tail -1
ok "Dependencies installed"

# --- Step 2: Start local services -------------------------------------------

step 2 "Starting local services..."

if [ "$HAS_SUPABASE" = true ]; then
  # Check Docker is running
  if ! docker info >/dev/null 2>&1; then
    fail "Docker is not running."
    echo ""
    echo "  Start Docker Desktop and wait for it to initialize, then re-run:"
    echo "    make verify-local"
    exit 1
  fi

  echo "  Starting local Supabase (this may take a minute on first run)..."
  npx supabase start -x realtime,storage,imgproxy,inbucket,pgadmin-schema-diff,migra,postgres-meta,studio,edge-runtime,logflare,pgbouncer,vector 2>&1 | tail -3
  SUPABASE_STARTED=true
  ok "Local Supabase started"

  echo "  Applying migrations..."
  npx supabase db reset 2>&1 | tail -3
  ok "Migrations applied"
else
  ok "No supabase/config.toml — skipping local database"
fi

# --- Step 3: Set up environment ---------------------------------------------

step 3 "Setting up environment..."

if [ "$HAS_ENV_EXAMPLE" = true ] && [ ! -f .env.local ]; then
  # Read local Supabase keys dynamically (supports CLI v2.76+ with sb_* keys)
  LOCAL_SUPABASE_URL="http://127.0.0.1:54321"
  LOCAL_SUPABASE_ANON_KEY=$(npx supabase status -o json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('ANON_KEY',''))" 2>/dev/null)
  if [ -z "$LOCAL_SUPABASE_ANON_KEY" ]; then
    # Fallback: legacy deterministic key (Supabase CLI <v2.76)
    LOCAL_SUPABASE_ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
  fi

  # Read .env.example line by line and substitute known local values
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      NEXT_PUBLIC_SUPABASE_URL=*)
        echo "NEXT_PUBLIC_SUPABASE_URL=$LOCAL_SUPABASE_URL" ;;
      NEXT_PUBLIC_SUPABASE_ANON_KEY=*)
        echo "NEXT_PUBLIC_SUPABASE_ANON_KEY=$LOCAL_SUPABASE_ANON_KEY" ;;
      *)
        echo "$line" ;;
    esac
  done < .env.example > .env.local

  ok "Generated .env.local from .env.example (local Supabase + placeholder analytics)"
elif [ -f .env.local ]; then
  ok ".env.local already exists — using existing values"
else
  ok "No .env.example — skipping environment setup"
fi

# --- Step 4: Run tests ------------------------------------------------------

step 4 "Running tests..."

DEV_PID=""

if [ "$HAS_PLAYWRIGHT" = true ]; then
  # Start dev server in background for E2E tests
  echo "  Starting dev server..."
  npm run dev -- -p 3000 >/dev/null 2>&1 &
  DEV_PID=$!

  # Wait for dev server to be ready
  echo "  Waiting for dev server on http://localhost:3000..."
  RETRIES=0
  MAX_RETRIES=30
  while ! curl -sf http://localhost:3000 >/dev/null 2>&1; do
    RETRIES=$((RETRIES + 1))
    if [ $RETRIES -ge $MAX_RETRIES ]; then
      fail "Dev server did not start within 30 seconds"
      kill $DEV_PID 2>/dev/null || true
      exit 1
    fi
    sleep 1
  done
  ok "Dev server ready"

  echo "  Running Playwright E2E tests..."
  if npx playwright test; then
    ok "E2E tests passed"
  else
    fail "E2E tests failed"
    echo ""
    echo "  To debug interactively:  npx playwright test --ui"
    echo "  To auto-fix with Claude: /verify"
    kill $DEV_PID 2>/dev/null || true
    exit 1
  fi

  kill $DEV_PID 2>/dev/null || true
else
  echo "  No playwright.config.ts — falling back to build check..."
  if npm run build; then
    ok "Build succeeded"
  else
    fail "Build failed"
    exit 1
  fi
fi

# --- Done --------------------------------------------------------------------

echo ""
echo -e "${GREEN}${BOLD}All checks passed!${NC}"
echo ""
echo "  Your app is working locally. Next steps:"
echo "    npm run dev              Start the dev server"
echo "    make deploy              Deploy to production"
echo ""
