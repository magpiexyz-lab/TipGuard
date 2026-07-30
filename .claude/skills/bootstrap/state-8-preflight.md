# STATE 8: PREFLIGHT

**PRECONDITIONS:**
- Plan saved with Process Checklist (STATE 7 POSTCONDITIONS met)

**ACTIONS:**

**Do NOT assemble file contents into the prompt.** Subagents are independent
Claude Code sessions with full file access — they read files themselves. The
prompt tells them WHICH files to read and WHAT to do.

> **WHY:** Embedded content becomes stale if files change between prompt
> construction and subagent execution. The subagent cannot verify embedded
> content matches disk, violating "observe, not trust." Embedded content
> also inflates prompt size, reducing the subagent's effective working
> memory (each 200 lines ~ 2 lost reasoning turns). Let subagents read.

1. **Production quality check**: Pass this flag to each scaffold-* agent prompt: "quality: production is active. Generate tests alongside each file you create." Agent test ownership:
   - scaffold-setup: create testing config (playwright.config.ts or vitest.config.ts)
   - scaffold-libs: generate unit tests for utility functions alongside library code
   - scaffold-pages: generate page-load smoke tests (thorough)
   - scaffold-wire: run test discovery checkpoint (`npx playwright test --list` or vitest equivalent)

   **Vitest co-installation**: If `stack.testing` is NOT `vitest` (e.g., `testing: playwright`):
   - Also install `vitest` and `@vitest/coverage-v8` as dev dependencies
   - Create `vitest.config.ts` using the template from `.claude/stacks/testing/vitest.md`
   - This ensures unit tests (TDD per `patterns/tdd.md`) can run alongside E2E tests
   - scaffold-setup handles this: check if vitest.config.ts exists before creating
   - Two test runners coexist: `npx playwright test` for E2E, `npx vitest run` for unit tests

2. **TSP-LSP check**: Run `which typescript-language-server`. If found, record
   `tsp_status: "available"`. If not found, tell the user:
   > `typescript-language-server` is not installed globally. It gives subagents
   > real-time type checking during code generation. Install with:
   > `npm install -g typescript-language-server typescript`
   > Say "skip" to proceed without it.
   Wait for the user to confirm installation or say "skip". If confirmed,
   re-check with `which typescript-language-server`. Record `tsp_status`
   as `"available"` or `"skipped"`.

This value is passed to subagents in their prompts (subagents cannot
interact with users).

Check off in `.runs/current-plan.md`: `- [x] TSP-LSP check completed`

3. **FAL_KEY check** (AI image generation): Check if `FAL_KEY` is available
   via persistent file (`~/.fal/key`) or environment variable.

   **Two-stage check** (issue #1388 — sandbox compatibility):
   The Claude Code sandbox classifier denies a single `python3 -c` block that
   reads `~/.fal/key` content because `f.read()` on a credential file IS
   credential exploration. Without a fallback, the lead silently chooses
   `image_gen_status: "skipped"` and ships SVG placeholders even when the
   key is present. The two-stage shape below: (a) Stage 1 uses `test -f` /
   `test -n` to determine PRESENCE without reading content (sandbox-safe);
   (b) Stage 2 reads the value ONLY when presence is confirmed (intent has
   shifted from "is there a key" exploration to "use the existing key"
   operational use, which the sandbox classifier accepts).

   **Stage 1 — Presence (sandbox-safe, no content read):**
   ```bash
   if test -f ~/.fal/key || test -n "${FAL_KEY:-}"; then
     PRESENCE=true
   else
     PRESENCE=false
   fi
   ```

   **Stage 2 — Validity (only when presence=true):**
   ```bash
   if [ "$PRESENCE" = true ]; then
     STATUS=$(python3 -c "
   import os
   v = ''
   try:
       with open(os.path.expanduser('~/.fal/key')) as f: v = f.read().strip()
   except FileNotFoundError: pass
   if not v: v = os.environ.get('FAL_KEY', '')
   print('available' if v and not v.startswith('placeholder') else 'missing')
   ")
   else
     STATUS=missing
   fi
   echo "$STATUS"
   ```

   **Stage 2 fallback** — if Stage 2 still hits a sandbox denial, do NOT
   silently fall through to `skipped`. Tell the user:
   > Sandbox blocked the Stage 2 validity read of `~/.fal/key`. Run this
   > yourself in your shell and tell me the output:
   > ```
   > bash -c 'test -f ~/.fal/key && head -c 8 ~/.fal/key'
   > ```
   > If you see a key prefix (not `placeholder`), respond `available`.
   > To proceed without AI images, respond `skip`.
   Wait for the user reply. Record the status accordingly. Failing to ask
   is the issue #1388 root failure mode (silent SVG ship).

   If `FAL_KEY` is available (STATUS=available), record `image_gen_status: "available"`.
   If `FAL_KEY` is not set (STATUS=missing AND PRESENCE=false), tell the user:
   > `FAL_KEY` is not set. AI image generation (FLUX.2 Pro via fal.ai) creates
   > custom hero images, feature illustrations, and empty state graphics during
   > bootstrap. Without it, themed SVG placeholders will be used instead.
   >
   > Get your key from https://fal.ai > Dashboard > Keys, then:
   > `export FAL_KEY=your-fal-ai-key`
   >
   > Say "skip" to proceed with SVG placeholders.
   Wait for the user to set the key or say "skip". If they provide it,
   persist for future sessions: `mkdir -p ~/.fal && echo "$FAL_KEY" > ~/.fal/key`
   Then re-check. Record `image_gen_status` as `"available"` or `"skipped"`.

   **Fallback reason recording** (issue #1388 defense-in-depth — closes
   silent-skip recurrence guard): when `image_gen_status` lands on `"skipped"`,
   ALSO record WHY in `bootstrap-context.json` so observer can surface the
   cause if the SAME silent skip recurs. Allowed values for `image_gen_fallback_reason`:

   - `"user_skipped"` — user explicitly typed "skip" (Stage 2 succeeded as
     missing, OR user declined to set the key when presented with the
     "FAL_KEY is not set" prompt above).
   - `"fal_key_missing"` — Stage 1 returned PRESENCE=false; user did not
     provide a key when prompted.
   - `"sandbox_denied"` — Stage 2 hit a sandbox denial AND user-fallback
     prompt also failed to resolve the status.
   - `"fal_api_error"` — reserved for scaffold-images runtime use; unused
     at preflight stage but kept in the enum for downstream consistency.

   This value is passed to subagents in their prompts (subagents cannot
   interact with users).

   This value is passed to subagents in their prompts (subagents cannot
   interact with users).

Check off in `.runs/current-plan.md`: `- [x] FAL_KEY check completed`

- **Record preflight results** in `bootstrap-context.json`:
  ```bash
  PAYLOAD=$(python3 -c "
  import json
  ctx = json.load(open('.runs/bootstrap-context.json'))
  ctx['preflight_passed'] = True
  ctx['image_gen_status'] = '<available_or_skipped>'
  # When image_gen_status == 'skipped', also record fallback_reason per #1388:
  # one of 'user_skipped' | 'fal_key_missing' | 'sandbox_denied' | 'fal_api_error'.
  # Omit the field when image_gen_status == 'available'.
  ctx['image_gen_fallback_reason'] = '<value-or-omit>'
  print(json.dumps(ctx))
  ")
  bash .claude/scripts/lib/write-gate-artifact.sh \
    --path .runs/bootstrap-context.json \
    --payload "$PAYLOAD" \
    --skill bootstrap
  ```
  Replace `<available_or_skipped>` with the actual value determined above.
  Replace `<value-or-omit>` with the fallback_reason enum value (or omit
  the field entirely when image_gen_status is `"available"`).

**POSTCONDITIONS:**
- `tsp_status` is set to `"available"` or `"skipped"`
- `image_gen_status` is set to `"available"` or `"skipped"`
- Quality flag recorded (production)
- `preflight_passed` field set to `true` in `bootstrap-context.json`

**VERIFY:**
```bash
python3 -c "import json; assert json.load(open('.runs/bootstrap-context.json')).get('preflight_passed') == True, 'preflight_passed not set'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh bootstrap 8
```

**NEXT:** Read [state-9-setup-phase.md](state-9-setup-phase.md) to continue.
