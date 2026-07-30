# STATE x4a: PERSIST_LEDGER

Persist each MVP's verdict + metrics snapshot + product description + classification
tags to a **durable, git-tracked** decision ledger
(`experiment/mvp-decision-ledger.jsonl`), so portfolio outcome data survives infra
teardown.

## Why this state exists

When an MVP is judged NO_GO, the operator typically tells the team to delete its
Supabase / Railway / Vercel infra to save cost — which destroys the PostHog/DB ground
truth. This state captures, **before** that deletion and committed to git, what each
MVP did and how it performed, building a reusable dataset for brainstorming and
pre-judging which new ideas are likely to succeed.

Semantics (operator-confirmed):
- **Non-destructive UPSERT** keyed by canonical MVP name (one row per MVP).
- `current` verdict+metrics overwritten each run; `verdict_history` appends a compact
  `{date,verdict,why}` only when the verdict/why changed (capped, dedup'd).
- `what_it_does` (mechanically parsed from the repo's `experiment.yaml`) and `tags`
  (lead-proposed enums) are **sticky** — never overwritten with empty; the repo may be
  gone on a later run.
- A row **freezes** (`archived_at` set) when the backend is killed or DB-deleted, so
  the pre-teardown snapshot is locked. Freeze is **reversible**: if trusted live DB
  ground truth reappears, the row un-freezes and resumes updating.
- **Promoted rows never freeze** (live Phase-2 projects; `is_deleted` is
  killed/deleted-only). The active→promoted transition appends one
  `{date, verdict: "PROMOTED", why: "operator confirmed promote..."}` event to
  `verdict_history` — detected on the run AFTER the operator confirms in x4
  (persist-lifecycle writes config; the next run's scores carry the status — a
  documented one-run lag; the config is the authoritative record at confirm
  time). `current.lifecycle_status` mirrors the decision state in the ledger.
- Orphans are skipped (no canonical identity, no repo); `ga_only` MVPs are included.

Mirrors x0c's `prepare → lead-extract → persist` shape and reuses
`resolve_repo` / `fetch_file` / `match_key` / `load_yaml`.

**PRECONDITIONS:**
- STATE x4 POSTCONDITIONS met (`.runs/iterate-cross-scores.json` exists with `headline_verdict` + `metrics` per MVP)
- `.runs/iterate-cross-data.json` exists (raw metrics; passed through for parity)

**ACTIONS:**

This state is best-effort on enrichment (repo fetch) but the upsert itself always
runs — every scored MVP gets a ledger row regardless of whether its description could
be fetched.

### Step 1: prepare the enrichment bundle

```bash
python3 .claude/scripts/lib/iterate_cross_ledger.py prepare \
  --scores .runs/iterate-cross-scores.json \
  --data .runs/iterate-cross-data.json \
  --ledger experiment/mvp-decision-ledger.jsonl \
  --config experiment/iterate-cross-config.yaml \
  --output .runs/_iterate-cross-ledger-input.json
```

This selects MVPs that need enrichment (incremental: rows missing sticky
`what_it_does`/`tags`, skipping frozen rows; add `--enrich-all` to re-fetch every
still-reachable repo — used for the one-time backfill). For each target it resolves
the canonical name to a `magpiexyz-lab` repo via the layered chain
(`resolve_repo_layered`: override > alias > exact-name > experiment.yaml
name-index > description prefix > homepage) and mechanically parses
`thesis`/`target_user`/`description`/`problem` from that repo's `experiment/experiment.yaml`
(no LLM). It writes `.runs/_iterate-cross-ledger-input.json` with `to_enrich` (need
tags) and `desc_only` (already tagged) buckets, plus the fixed `tag_vocab`.

Best-effort: if `gh` is unavailable, a repo doesn't match, or the file 404s, the parsed
description is empty — the row still upserts and its sticky fields are left untouched.

### Step 2: lead proposes classification tags (inline, like x2/x0c)

Read `.runs/_iterate-cross-ledger-input.json`. For **each** MVP in `to_enrich`, inspect
its `snippet_for_tags` (thesis, target_user, signup_events, price) and choose ONE value
per dimension **from the fixed enum vocab in `tag_vocab`** (out-of-vocab values are
dropped by persist with a warning):

- `vertical` — the product's market/domain (e.g. `ai-content`, `dev-tools`, `fintech`, `vertical-saas`, …; `other` when none fit).
- `gtm` — the go-to-market motion (`waitlist`, `self-serve-signup`, `demo-led`, `free-tool`, `marketplace`, `api-access`).
- `pricing_model` — `subscription`, `one-time`, `usage-based`, `freemium`, or `none-waitlist`.

Write `.runs/_iterate-cross-ledger-proposals.json` as a JSON array:

```json
[
  {"mvp": "stylica-ai", "vertical": "ai-content", "gtm": "self-serve-signup", "pricing_model": "subscription"},
  {"mvp": "dsar-flow", "vertical": "compliance-legal", "gtm": "waitlist", "pricing_model": "none-waitlist"}
]
```

An empty array (`[]`) is acceptable (tags stay empty; mechanical description still
persists). Only MVPs in `to_enrich` need a proposal.

### Step 3: persist (non-destructive upsert)

```bash
python3 .claude/scripts/lib/iterate_cross_ledger.py persist \
  --scores .runs/iterate-cross-scores.json \
  --data .runs/iterate-cross-data.json \
  --ledger experiment/mvp-decision-ledger.jsonl \
  --config experiment/iterate-cross-config.yaml \
  --input .runs/_iterate-cross-ledger-input.json \
  --proposals .runs/_iterate-cross-ledger-proposals.json
```

Upserts every scored MVP (skipping orphans) into the jsonl, sorted by `mvp` for clean
diffs. Frozen rows keep their pre-teardown `current`/`verdict_history`/sticky fields;
killed/DB-deleted MVPs get `archived_at` stamped. Idempotent — re-running with the same
scores adds no duplicate history rows.

The ledger is committed to git by `lifecycle-finalize.sh` along with the rest of the
run's changes (it lives under `experiment/`, which is tracked).

### Cleanup

```bash
rm -f .runs/_iterate-cross-ledger-input.json .runs/_iterate-cross-ledger-proposals.json
```

**POSTCONDITIONS:**
- `experiment/mvp-decision-ledger.jsonl` exists; every line is valid JSON; no duplicate `mvp` keys
- Every row has `mvp`, `current` (dict), `verdict_history` (list), `what_it_does` (dict), `tags` (dict)
- Killed / DB-deleted MVPs carry a non-null `archived_at` (frozen)

**VERIFY:** see `state-registry.json` entry for `iterate-cross.x4a`.

```bash
test -f experiment/mvp-decision-ledger.jsonl && python3 -c "import json; seen=set(); rows=[json.loads(l) for l in open('experiment/mvp-decision-ledger.jsonl') if l.strip()]; assert rows, 'ledger empty'; [seen.add(r['mvp']) for r in rows]; assert len(seen)==len(rows), 'duplicate mvp keys in ledger'; bad=[r.get('mvp','?') for r in rows if not r.get('mvp') or not isinstance(r.get('current'),dict) or not isinstance(r.get('verdict_history'),list) or not isinstance(r.get('what_it_does'),dict) or not isinstance(r.get('tags'),dict)]; assert not bad, 'ledger rows missing required fields: %s' % bad"
```
<!-- VERIFY=true: real assertion lives in state-registry.json; this line is the per-Rule-13 placeholder -->

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh iterate-cross x4a
```

**NEXT:** Read [state-x4b-reconcile-teardown.md](state-x4b-reconcile-teardown.md) to continue.
