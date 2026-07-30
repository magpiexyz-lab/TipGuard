# STATE 11: CORE_SCAFFOLD

**PRECONDITIONS:**
- Design done (STATE 10 POSTCONDITIONS met)
- `.runs/current-visual-brief.md` exists
- Theme tokens available

**ACTIONS:**

#### Phase A (serial, before fan-out, web-app only)

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Phase A (core scaffold)".
>
> [phase-a] web-app: run (layout, 404, error, favicon, OG, sitemap, robots, llms.txt) | service: skip | cli: skip

Service and cli archetypes skip Phase A entirely — proceed to STATE TRACKING to advance state immediately.

The lead (not a subagent) creates:
- Root layout (`src/app/layout.tsx`) with font imports and globals.css
- 404 page (`src/app/not-found.tsx`)
- Error boundary (`src/app/error.tsx`)
- Favicon (`src/app/icon.tsx`) -- monogram of project name initial in primary color, 128x128, using `ImageResponse` from `next/og`. Uses a system font (sans-serif) -- do NOT fetch Google Fonts in Satori context. Read primary color from `globals.css` `--primary` token or hardcode the derived value.
- OG image (`src/app/opengraph-image.tsx`) -- 1200x630 branded card with project name centered on primary-color gradient background. Uses `ImageResponse` from `next/og` with system font.
- Robots (`src/app/robots.ts`) -- Next.js built-in robots.txt, allow all crawlers for MVP
- llms.txt (`public/llms.txt`) -- static AI-readable product summary per messaging.md Section E
- Variant routing files (if `variants` in experiment.yaml): `src/lib/variants.ts`, `src/app/page.tsx`, `src/app/v/[variant]/page.tsx`

Phase A runs AFTER scaffold-init completes (STATE 10) to ensure design tokens exist.

After creating all Phase A files, run the **build self-check** (EARC slice 2 / Half I, closes #1182 root cause): `npm run build` MUST exit 0 before sealing the Phase A sentinel. Invalid Phase A files (e.g., `next/font` config errors) thus cannot escape into the sealed window where downstream subagents can no longer fix them.

**On failure, the lead does NOT bypass — it repairs and retries.** The procedure:

1. Read the build log (last 30 lines printed to stderr by the snippet below).
2. Identify the failing Phase A file from the error.
3. Use the `Edit` or `Write` tool to fix the file in-place. **No gate applies yet** because `phase-a-sentinel.json` has not been written; the no-rewrite window is not active.
4. Re-execute the build self-check snippet below until it passes.
5. Sentinel writes only after the snippet exits 0; lead advances state only after that.

If repair attempts exceed three rounds without convergence, the lead writes a `recovery` trace via `write-recovery-trace.sh` rather than continuing to retry — that's the cross-skill recovery path, not a bypass.

```bash
mkdir -p .runs/gate-verdicts

# EARC Half I: build self-check before sealing Phase A.
# Failure: lead must repair the file(s) in-place and re-run this snippet.
# DO NOT bypass via shell write (python -c, sed -i, cat >) — those are
# blocked by the bootstrap-phase-a-write-guard.sh hook in deny mode.
if ! npm run build > /tmp/phase-a-build.log 2>&1; then
  echo "ERROR: state-11 build self-check failed; Phase A cannot be sealed." >&2
  echo "       Repair the failing file(s) below using the Edit/Write tool" >&2
  echo "       and re-run this snippet. NO sentinel will be written until" >&2
  echo "       npm run build exits 0." >&2
  echo "--- npm run build (tail) ---" >&2
  tail -30 /tmp/phase-a-build.log >&2
  exit 1
fi
echo "state-11 build self-check passed."

bash .claude/scripts/archive-gate-verdict.sh phase-a-sentinel
CORE_FILES='["src/app/layout.tsx","src/app/not-found.tsx","src/app/error.tsx","src/app/icon.tsx","src/app/opengraph-image.tsx","src/app/robots.ts","public/llms.txt"'
if grep -q '^variants:' experiment/experiment.yaml 2>/dev/null; then
  CORE_FILES+=',"src/lib/variants.ts","src/app/page.tsx","src/app/v/[variant]/page.tsx"'
fi
CORE_FILES+=']'
COMMIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
PAYLOAD=$(COMMIT_SHA_ENV="$COMMIT_SHA" CORE_FILES_ENV="$CORE_FILES" python3 -c "
import json, os, datetime
print(json.dumps({
    'phase_a_complete': True,
    'build_passing': True,
    'commit_sha': os.environ['COMMIT_SHA_ENV'],
    'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'files': json.loads(os.environ['CORE_FILES_ENV']),
}))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/gate-verdicts/phase-a-sentinel.json \
  --payload "$PAYLOAD" \
  --skill bootstrap
```

The sentinel's `build_passing: true` field is a usability attestation: it proves Phase A files compiled successfully at seal time. Slice 3's gate-side EARC reads this attestation when evaluating evidence-anchored repair requests for residual cases (post-seal regressions, runtime-only failures invisible to `npm run build`, upstream dependency drift).

VERIFY Phase A before proceeding (**web-app only** — service and cli archetypes skip this entire block since they skip Phase A):
- `test -f src/app/layout.tsx`
- `test -f src/app/not-found.tsx`
- `test -f src/app/error.tsx`
- `test -f src/app/icon.tsx`
- `test -f src/app/opengraph-image.tsx`
- `test -f src/app/robots.ts`
- `test -f public/llms.txt`
- `test -f .runs/gate-verdicts/phase-a-sentinel.json`
- If `variants` is present in experiment.yaml: `test -f src/lib/variants.ts && test -f src/app/page.tsx && test -f "src/app/v/[variant]/page.tsx"`

> **Sitemap.ts authorship moved to state-11c post-fan-out (#1387)**: previously listed here as a Phase A file. Moving it allows the emitter to consume `dynamic_public_pages()` for fixture-slug enumeration of dynamic-segment routes, which requires Phase B2 fixtures to exist. State-11c post-fan-out writes `src/app/sitemap.ts`.

**POSTCONDITIONS:**
- Phase A sentinel written (web-app) or skipped (service/cli)
- Core files created (web-app only)
- `npm run build` passing at seal time (web-app only) — `phase-a-sentinel.json.build_passing == true`

**VERIFY:**
```bash
python3 -c "import json,os; a=json.load(open('.runs/bootstrap-context.json')).get('archetype','web-app'); s='.runs/gate-verdicts/phase-a-sentinel.json'; assert a!='web-app' or (os.path.isfile(s) and json.load(open(s)).get('build_passing') is True), 'phase-a-sentinel missing or build_passing!=true (EARC slice 2 / closes #1182 root cause)'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 11
```

**NEXT:** Read [state-11a-lib-spawn.md](state-11a-lib-spawn.md) to continue.
