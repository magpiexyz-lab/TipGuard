---
name: step55-evidence-gotchas
description: Two things that silently fail validate-step55-evidence.py in this repo - provenance filename convention and the ~8KB trace payload cap
metadata:
  type: project
---

Running Step 5.5 correctly is not enough to pass `.claude/scripts/validate-step55-evidence.py`
in this working copy. Two mechanical traps, both observed 2026-08-11.

**1. Provenance filename convention mismatch.**
scaffold-images writes `.runs/image-candidates/<name>.<ext>.provenance.json`
(e.g. `hero-exploit-2.webp.provenance.json`). `.claude/scripts/lib/phash.py`
`read_provenance()` does `os.path.splitext(image_path)` and looks for
`hero-exploit-2.provenance.json`. The validator then emits `missing_provenance`
for every candidate and `continue`s *before* incrementing `evidence_seen`, so it
also emits a false `sampling_floor_unmet` for every slot.

**Why:** producer and consumer disagree on the naming rule; nothing reconciles them.
**How to apply:** after annotating the sidecar, duplicate each provenance file to
the splitext name before running the validator. Verify with
`STEP55_EVIDENCE_MODE=deny python3 .claude/scripts/validate-step55-evidence.py`
(exit 0 = clean) rather than trusting warn mode.

**2. Trace payload cap.** `write-agent-trace.sh --json` truncates past ~8.1 KB on
this msys/Git Bash argv path. Keep the serialized payload under ~8000 chars and use
`json.dumps(..., separators=(",", ":"))`. Also strip apostrophes from prose - the
bash layer mangles them into `\'` and breaks the parse. See
[[render-surface-contention]] for the other reliability trap in this flow.
