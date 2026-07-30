"""RMG v2 Layer 1 — Prior-Failure Dossier builder.

Produces a two-phase dossier consumed by `solve-reasoning` Phase 1a and
Phase 4b. Phase 1a withholds failure-mode prose to keep the designer's
first pass independent (anchoring resistance — Round-2 critic concern
R2-A2). Phase 4b adds the prose for the cross-check pass.

Public API:

    build_dossier(divergence_files, symptom_signature, project_dir, *,
                  ledger_path=None, candidates_path=None, now=None)
        -> {"phase_1a": [...], "phase_4b": [...]}

Each entry mirrors the others — phase_4b is a strict superset of phase_1a:

    {
      "prior_run_id": str,         # "<skill>-<ts>" for ledger entries OR
                                    # "git:<sha[:7]>" for git-history-augmented
                                    # entries (#1437 fix). The "git:" sentinel
                                    # tells consumers the entry was synthesized
                                    # from VCS history rather than the ledger,
                                    # and is **advisory** — solve-critic vector 4
                                    # excludes git-sentinel entries from its
                                    # response-floor (dossier_verify mirrors).
      "files_touched": [str, ...],
      "regression_test_present": bool,
      "occurrence_count_60d": int,
      # phase_4b only:
      "failure_mode": str,
      "what_was_missed": str,
      "prior_commit_sha": str | None,
    }

Sources:
  * `.runs/fix-ledger.jsonl` — rows whose `file` ∈ `divergence_files`.
    Filtered scope: cross-run by design — the dossier wants prior fix
    attempts regardless of which run produced them.
  * `.runs/recurrence-candidates.jsonl` — rows whose composite_identity_hash
    matches any composite derived from the divergence_files set.
  * git log on each divergence file (#1437; cap max_per_file=5 via
    `runs_reader.read_git_log`) — surfaces history that would otherwise
    be hidden when the ledger is empty (the silent-empty path the
    original implementation hit). Best-effort: missing/non-repo → [].

`regression_test_present` is True iff the prior run's `solve-trace.json` had
a `recurrence_guard.kind ∈ {test, hook, invariant}` with non-null artifact.
Solve-trace.json files are typically gitignored, so this signal is best-effort
and falls back to False.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# Re-use the symptom canonicalizer + compute_hash that ship with Phase B/A.
sys.path.insert(0, str(HERE))
from symptom_canonicalizer import canonicalize_symptom  # noqa: E402

REPO_ROOT_FALLBACK = HERE.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT_FALLBACK / "scripts" / "lib"))
from stack_knowledge_parser import compute_hash  # noqa: E402

# Recurrence guard parser is sibling — used to read prior solve-trace.json
sys.path.insert(0, str(HERE))
try:
    from recurrence_guard_parser import RecurrenceGuardParseError, parse as _parse_guard
except ImportError:  # parser ships in Phase A; tolerate missing
    _parse_guard = None
    RecurrenceGuardParseError = Exception  # type: ignore[misc,assignment]

DOSSIER_WINDOW_DAYS_DEFAULT = 60


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _stack_scope_for_file(file_path: str) -> str:
    if not file_path:
        return "unknown"
    parts = Path(file_path).parts
    if len(parts) <= 1:
        return parts[0] if parts else "unknown"
    return "/".join(parts[:2])


def _composite_hash_for_row(row: dict) -> str:
    composite = {
        "root_cause_class": row.get("severity") or "warn",
        "divergence_pattern": canonicalize_symptom(row.get("symptom") or ""),
        "stack_scope": _stack_scope_for_file(row.get("file") or ""),
    }
    return compute_hash(composite)


def _regression_test_present_for(run_id: str, project_dir: Path) -> bool:
    """Best-effort: open a prior run's solve-trace.json and inspect the guard.

    solve-trace.json is per-run and gitignored, so the file rarely persists
    across runs. Treat absence as False.
    """
    trace_path = project_dir / ".runs" / "solve-trace.json"
    if not trace_path.exists():
        return False
    try:
        data = json.loads(trace_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("run_id") != run_id:
        return False
    pa = data.get("prevention_analysis") or {}
    guard = pa.get("recurrence_guard")
    if guard is None or _parse_guard is None:
        return False
    try:
        canonical = _parse_guard(guard)
    except RecurrenceGuardParseError:
        return False
    kind = canonical.get("kind")
    artifact = canonical.get("artifact")
    return kind in ("test", "hook", "invariant") and bool(artifact)


def _git_log_for_files(files: list[str], project_dir: Path, *, since_days: int) -> dict[str, str]:
    """Return {commit_sha: subject} for commits touching any of `files` in window."""
    if not files:
        return {}
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%d")
    cmd = [
        "git",
        "-C",
        str(project_dir),
        "log",
        "--since",
        since,
        "--pretty=format:%H\t%s",
        "--",
        *files,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for line in result.stdout.splitlines():
        sha, _, subject = line.partition("\t")
        if sha:
            out[sha] = subject
    return out


def _summarize_failure_mode(row: dict) -> str:
    symptom = row.get("symptom") or row.get("desc") or row.get("description") or ""
    fix = row.get("fix") or ""
    if symptom and fix:
        return f"{symptom.strip()[:120]} — prior fix: {fix.strip()[:80]}"
    return symptom.strip()[:200] or "(no symptom recorded)"


def _summarize_what_was_missed(rows: list[dict]) -> str:
    if not rows:
        return ""
    fixes = [r.get("fix") or r.get("action") for r in rows if r.get("fix") or r.get("action")]
    fixes = [f.strip() for f in fixes if isinstance(f, str)]
    if not fixes:
        return "prior fix attempts did not record a fix description"
    head = fixes[0][:120]
    if len(fixes) > 1:
        return f"prior attempts: {head} (+{len(fixes) - 1} more); recurrence indicates the guard did not hold"
    return f"prior attempt: {head}; recurrence indicates the guard did not hold"


# Sentinel tokens emitted by symptom_canonicalizer.canonicalize_symptom().
# Excluded from semantic-match scoring because they appear in every canonicalized
# symptom and would inflate the overlap score without indicating real relevance.
_SYMPTOM_SENTINEL_TOKENS = frozenset({
    "<TS>", "<PATH>", "<SHA>", "<LINE>", "<COL>",
})

# Stop-words that appear in too many commit subjects to be discriminating.
_SEMANTIC_MATCH_STOPWORDS = frozenset({
    "fix", "fixes", "fixed", "feat", "chore", "refactor", "docs", "test", "tests",
    "the", "a", "an", "and", "or", "of", "in", "to", "for", "with", "from",
    "add", "remove", "update", "change", "use", "via", "by", "on",
})


def _tokenize_for_semantic_match(text: str) -> set[str]:
    """Extract content tokens (lowercase, ≥3 chars, no sentinels, no stopwords).

    Used by `_compute_semantic_match` to score overlap between a canonicalized
    symptom signature and a prior commit's subject. The set form lets us use
    set-intersection cardinality as the overlap metric.
    """
    if not isinstance(text, str):
        return set()
    import re as _re
    lowered = text.lower()
    # Strip sentinel tokens like <ts>, <path>, <sha>
    for sent in _SYMPTOM_SENTINEL_TOKENS:
        lowered = lowered.replace(sent.lower(), " ")
    # Split on non-alnum (including hyphens) so compound tokens like
    # "post-completion" and "--source-run-id" decompose into their content
    # words. This is critical for the overlap heuristic: symptom signatures
    # like "post-completion identity-resolution" must match commit subjects
    # like "writer identity overrides" via the "identity" word, not require
    # the entire compound to be identical.
    tokens = {
        t for t in _re.split(r"[^a-z0-9]+", lowered)
        if len(t) >= 3 and t not in _SEMANTIC_MATCH_STOPWORDS
    }
    return tokens


def _compute_semantic_match(
    symptom_signature: str,
    commit_subject: str,
    files_touched: list[str],
    divergence_files: set[str] | list[str],
    *,
    min_token_overlap: int = 2,
) -> bool:
    """Return True iff the prior commit's subject semantically matches the
    current symptom signature.

    Heuristic (#1468/#1456 root-cause analysis closure):
      - Tokenize both symptom_signature and commit_subject into content
        tokens (excluding sentinels + stopwords + tokens shorter than 3 chars).
      - Require ≥ min_token_overlap content-token overlap.
      - Require ≥1 file in `files_touched` matches `divergence_files` (always
        true by construction since the dossier only includes co-touched files,
        but kept here as a defensive invariant).

    Returns True only when BOTH conditions hold — preventing false positives
    from file-name-only co-occurrence (the original RMG v2 git-sentinel
    "advisory" mode that this annotation reinforces).

    When True, `solve-critic` vector 4 escalates the entry from advisory to
    REQUIRED consultation; the designer must emit a `prior_failure_consultation`
    entry in solve-trace.json with `consulted_via != "skipped"` OR a
    `skip_justification` ≥40 chars.
    """
    if not symptom_signature or not commit_subject:
        return False
    symptom_tokens = _tokenize_for_semantic_match(symptom_signature)
    subject_tokens = _tokenize_for_semantic_match(commit_subject)
    overlap = symptom_tokens & subject_tokens
    if len(overlap) < min_token_overlap:
        return False
    file_set = set(divergence_files) if divergence_files else set()
    if not file_set or not files_touched:
        return False
    return any(
        f in file_set or any(f.startswith(d.rstrip("/") + "/") for d in file_set)
        for f in files_touched
    )


def build_dossier(
    divergence_files: list[str],
    symptom_signature: str,
    project_dir: str | os.PathLike | None = None,
    *,
    ledger_path: str | os.PathLike | None = None,
    candidates_path: str | os.PathLike | None = None,
    since_days: int = DOSSIER_WINDOW_DAYS_DEFAULT,
    now: datetime | None = None,
) -> dict:
    """Return a two-phase dossier for the given divergence files + symptom."""
    project_dir = Path(project_dir or os.getcwd()).resolve()
    ledger = Path(ledger_path) if ledger_path else project_dir / ".runs" / "fix-ledger.jsonl"
    candidates = Path(candidates_path) if candidates_path else project_dir / ".runs" / "recurrence-candidates.jsonl"
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=since_days)
    file_set = set(divergence_files or [])

    rows = _read_jsonl(ledger)
    cand_rows = _read_jsonl(candidates)

    # Index candidates by composite_identity_hash for fast lookup.
    candidate_by_hash: dict[str, dict] = {}
    for cand in cand_rows:
        chash = cand.get("composite_identity_hash")
        if isinstance(chash, str):
            candidate_by_hash[chash] = cand

    matched_by_run: dict[str, dict] = {}
    for row in rows:
        if row.get("entry_type") == "template-edit":
            continue
        ts = _parse_timestamp(row.get("timestamp"))
        if ts is not None and ts < cutoff:
            continue
        row_file = row.get("file") or ""
        chash = _composite_hash_for_row(row)
        in_candidate = chash in candidate_by_hash
        in_files = row_file in file_set or any(row_file.startswith(f.rstrip("/") + "/") for f in file_set)
        if not (in_candidate or in_files):
            continue
        run_id = row.get("run_id") or "<unknown>"
        bucket = matched_by_run.setdefault(
            run_id,
            {"rows": [], "files": set(), "first": None, "last": None, "composite_hash": chash},
        )
        bucket["rows"].append(row)
        if row_file:
            bucket["files"].add(row_file)
        if ts is not None:
            if bucket["first"] is None or ts < bucket["first"]:
                bucket["first"] = ts
            if bucket["last"] is None or ts > bucket["last"]:
                bucket["last"] = ts

    # Per-composite count (for occurrence_count_60d)
    composite_run_count: dict[str, set[str]] = {}
    for run_id, bucket in matched_by_run.items():
        composite_run_count.setdefault(bucket["composite_hash"], set()).add(run_id)

    sha_by_subject = _git_log_for_files(sorted(file_set), project_dir, since_days=since_days)
    sha_list = list(sha_by_subject.keys())

    phase_1a: list[dict] = []
    phase_4b: list[dict] = []
    for run_id, bucket in sorted(matched_by_run.items()):
        files = sorted(bucket["files"])
        composite_hash = bucket["composite_hash"]
        occurrences = len(composite_run_count.get(composite_hash, {run_id}))
        regression_test = _regression_test_present_for(run_id, project_dir)
        # Per-bucket SHA: best-effort attribution. Picks the most-recent SHA
        # not already attributed to an earlier bucket. Replaces the line-269 bug
        # where `next(iter(sha_by_subject.keys()), None)` always picked the
        # first SHA regardless of which bucket owned it. When no ledger entries
        # exist the loop never fires and git history surfaces via the
        # git-history-augmented block below.
        seen_so_far = {e["prior_commit_sha"] for e in phase_4b if e.get("prior_commit_sha")}
        prior_commit = next((s for s in sha_list if s not in seen_so_far), None)
        sample = bucket["rows"][0]

        failure_mode = _summarize_failure_mode(sample)
        # OARC #1468/#1456: annotate semantic-match for designer-consultation
        # gating. Ledger entries are already response-required (not advisory)
        # per solve-critic vector 4, so attestation_required is independent of
        # the response-floor — set True iff the canonicalized symptom and the
        # bucket's failure_mode share ≥2 content tokens AND ≥1 file overlap.
        attestation_required = _compute_semantic_match(
            symptom_signature, failure_mode, files, file_set,
        )
        slim = {
            "prior_run_id": run_id,
            "files_touched": files,
            "regression_test_present": regression_test,
            "occurrence_count_60d": occurrences,
            "designer_consultation_attestation_required": attestation_required,
        }
        full = dict(slim)
        full["failure_mode"] = failure_mode
        full["what_was_missed"] = _summarize_what_was_missed(bucket["rows"])
        full["prior_commit_sha"] = prior_commit
        phase_1a.append(slim)
        phase_4b.append(full)

    # Git-history-augmented entries (#1437 fix): index commits not represented
    # in the ledger-derived buckets above. Each entry carries the
    # `prior_run_id="git:<sha[:7]>"` sentinel so consumers (dossier_verify,
    # solve-critic vector 4) can distinguish ledger from git-derived provenance.
    # Capped at max_per_file=5 to avoid designer-burden cliff (see dossier_verify
    # relaxation: git-sentinel entries are advisory, not response-required).
    try:
        from runs_reader import read_git_log  # noqa: E402 — Phase A library
        git_entries = read_git_log(
            sorted(file_set),
            since_days=since_days,
            max_per_file=5,
            project_dir=str(project_dir),
        )
    except ImportError:
        git_entries = []
    already_seen_shas = {e["prior_commit_sha"] for e in phase_4b if e.get("prior_commit_sha")}
    for entry in git_entries:
        if entry["sha"] in already_seen_shas:
            continue
        already_seen_shas.add(entry["sha"])
        # OARC #1468/#1456: semantic-match annotation. Git-sentinel entries
        # default to advisory (vector 4); when this flag is True the entry
        # escalates to REQUIRED consultation. Computed from the commit subject
        # vs the canonicalized symptom signature.
        attestation_required = _compute_semantic_match(
            symptom_signature, entry.get("subject", ""), entry.get("files") or [], file_set,
        )
        slim = {
            "prior_run_id": f"git:{entry['sha'][:7]}",
            "files_touched": entry["files"],
            "regression_test_present": False,
            "occurrence_count_60d": 1,
            "designer_consultation_attestation_required": attestation_required,
        }
        full = dict(slim)
        full["failure_mode"] = entry["subject"][:200]
        full["what_was_missed"] = (
            f"prior commit on these files; consult `git show {entry['sha'][:7]}` for details"
        )
        full["prior_commit_sha"] = entry["sha"]
        phase_1a.append(slim)
        phase_4b.append(full)

    return {
        "phase_1a": phase_1a,
        "phase_4b": phase_4b,
        "_meta": {
            "divergence_files": sorted(file_set),
            "symptom_signature": symptom_signature,
        },
    }


__all__ = ["build_dossier", "DOSSIER_WINDOW_DAYS_DEFAULT"]
