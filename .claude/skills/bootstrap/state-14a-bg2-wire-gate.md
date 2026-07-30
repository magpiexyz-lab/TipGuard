# STATE 14a: BG2_WIRE_GATE

**PRECONDITIONS:**
- State 14 complete (scaffold-wire spawned)
- `.runs/agent-traces/scaffold-wire.json` exists with `verdict: "pass"` and `result: "clean"`
- `.runs/bootstrap-wire-trace.json` exists (written by state-14)

**ACTIONS:**

## Archetype Gate

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, rows "Primary unit".
> [primary-unit] web-app: page (`src/app/<page>/page.tsx`) | service: endpoint (`src/app/api/<ep>/route.ts`) | cli: command (`src/commands/<cmd>.ts`)
>
> State-specific logic below takes precedence.

Follow gate execution procedure per `procedures/gate-execution.md`.

Spawn the `gate-keeper` agent (`subagent_type: gate-keeper`). Pass: "Execute BG2-WIRE Post-Wire Gate. Verify: wire-produced artifacts. (1) src/components/nav-bar.tsx contains the {/* DERIVED-FROM: derive_scope_pages */} marker AND every canonical non-auth/non-landing page slug appears as href in nav-bar (web-app + stack.auth only); (2) src/app/api/ has route files for every mutation behavior (web-app/service); (3) src/index.ts + src/commands/ files exist (cli only); (4) all internal hrefs in pages resolve to existing routes including /auth/callback and /auth/reset-password (no exclusions — wire has run); dynamic segments like /dashboard/[id] are normalized to /dashboard/ before path-existence check; (5) post-wire `npm run build` passes (defense-in-depth re-run); (6) bootstrap-wire-trace.json has non-empty archetype-specific wired list (pages_wired for web-app, api_routes_wired for service, commands_wired for cli)."

> **Note:** This gate is the post-wire complement of BG2 (state-13c). BG2 verifies pre-wire scaffolds (libs, pages, landing); BG2-WIRE verifies wire-produced artifacts. The split closes #1142 — BG2 cannot assert artifacts whose producer (scaffold-wire) has not yet run when BG2 fires.

If gate-keeper returns BLOCK, fix wire output before proceeding (re-run scaffold-wire if missing artifacts; debug build errors locally).

Check off in `.runs/current-plan.md`: `- [x] BG2-WIRE Post-Wire Gate passed`

**POSTCONDITIONS:**
- BG2-WIRE Post-Wire Gate verdict is PASS

**VERIFY:**
```bash
python3 -c "import json; d=json.load(open('.runs/gate-verdicts/bg2-wire.json')); assert d.get('verdict')=='PASS', 'BG2-WIRE verdict is %s' % d.get('verdict'); assert d.get('timestamp','')!='', 'timestamp empty'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 14a
```

**NEXT:** Read [state-15-scan-and-classify.md](state-15-scan-and-classify.md) to continue.
