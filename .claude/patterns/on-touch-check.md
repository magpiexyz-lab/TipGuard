# ON-TOUCH Check Pattern

When `experiment/on-touch.yaml` exists, files marked as ON-TOUCH require
unit tests before modification. This pattern is checked at the start
of every production-quality change (Feature, Fix, Upgrade).

## Protocol

1. **Read** `experiment/on-touch.yaml`. If the file does not exist, skip.

2. **Prune stale entries.** Remove any entry whose `path` no longer exists on disk.
   Files may have been deleted since the ON-TOUCH list was created.

3. **Check overlap.** Compare the implementation plan's file list against the
   `on_touch` entries. Identify any files that appear in both.

4. **Add TDD prerequisite.** For each overlapping file: add a prerequisite TDD task
   to write unit tests for the existing code in that file BEFORE writing
   new feature/fix/upgrade code. This ensures existing behavior is captured before
   modification.

5. **Remove processed entry.** After the TDD task is added, remove the entry from
   the `on_touch` list.

6. **Clean up.** If the `on_touch` list is now empty, delete
   `experiment/on-touch.yaml` entirely.

## File Format

```yaml
on_touch:
  - path: src/app/api/invoices/route.ts
    reason: "Read-only GET, no mutations — deferred from bootstrap"
  - path: src/lib/utils.ts
    reason: "Simple utility, low risk"
```

## When ON-TOUCH Entries Are Created

ON-TOUCH entries are created during `/bootstrap` (STATE 17) for modules
classified as low-risk and deferred from immediate unit test generation.
See `.claude/skills/bootstrap/state-17-persist-on-touch.md`.

## Parameterization by Change Type

The pattern applies identically to Feature, Fix, and Upgrade changes. The only
difference is which procedure invokes it:
- Feature: `.claude/procedures/change-feature.md`
- Fix: `.claude/procedures/change-fix.md`
- Upgrade: `.claude/procedures/change-upgrade.md`
