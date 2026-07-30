#!/usr/bin/env python3
"""verify-linter runner — extracted from the verify-linter.sh heredoc.

PR2 commit 1: lifts the 1500-line Python heredoc out of the bash wrapper so
the linter logic is importable, testable, and refactorable. This commit is a
verbatim translation: zero behavior change. Subsequent commits split the
runner into context, utils, output, subsys A/B/C, and cross_file submodules.

Entry point: main() — invoked by .claude/scripts/lib/linter/cli.py via the
bootstrap shim that sets sys.path so this module can be imported.

Reads VL_* environment variables exported by verify-linter.sh:
  VL_JSON_OUT, VL_CACHE_FILE, VL_WARN_ONLY, VL_STRICT_AOC, VL_RULES_PATH,
  VL_REPO_ROOT.
"""


def main() -> int:
    import json, sys, os, glob, re

    # Repo root + derived paths come from VL_REPO_ROOT (exported by the bash
    # wrapper) or fall back to __file__-relative resolution. Same defaults the
    # heredoc used to compute via sys.argv[1-3].
    REPO_ROOT = os.environ.get(
        "VL_REPO_ROOT",
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    )
    registry_path = os.path.join(REPO_ROOT, ".claude", "patterns", "state-registry.json")
    skills_dir = os.path.join(REPO_ROOT, ".claude", "skills")
    patterns_dir = os.path.join(REPO_ROOT, ".claude", "patterns")

    # CLI flags exported from the bash wrapper
    JSON_OUT = bool(os.environ.get("VL_JSON_OUT"))
    CACHE_FILE = os.environ.get("VL_CACHE_FILE", "")
    WARN_ONLY = bool(os.environ.get("VL_WARN_ONLY"))
    STRICT_AOC = bool(os.environ.get("VL_STRICT_AOC"))
    RULES_PATH = os.environ.get("VL_RULES_PATH", "")
    # STRICT_AOC_TYPES is derived from HANDLERS below (single source of truth);
    # its forward reference works because _is_aoc_finding (the only consumer)
    # is defined after HANDLERS, so the name is bound by the time the function
    # is called.
    # REPO_ROOT already computed above (line ~24)

    registry = json.load(open(registry_path))

    # Keys that are not skills (no state files)
    SKIP_KEYS = {"trace_schemas"}

    uncovered = []
    diverged = []
    unjustified_true = []
    drift_declared = []
    cross_file = []

    # Phrases that count as matching prose for a declared `allows_early_exit_when` value.
    # The declared value itself (with _ replaced by space) is always matched; this dict
    # augments with common synonyms for known values.
    SYNONYMS = {
        "no_fixes": ["no fixes succeeded", "0 fixes", "zero fixes", "no fixes applied"],
        "zero_findings": ["0 remaining findings", "zero findings", "no findings"],
        "baseline_unchanged": ["error count same or decreased", "final_errors <= baseline", "no regression"],
        "all_fixes_rejected": ["all fixes were rejected", "no changes to commit", "no changes in git working tree"],
    }

    # Regex markers that must appear in a state's VERIFY for a declared `verify_semantics` value.
    VERIFY_SEMANTIC_MARKERS = {
        "strict_zero": [r"exit\s+0", r"&&\s*python3\s+scripts/validate", r"==\s*0"],
        "no_regression_from_baseline": [r"baseline", r"<=\s*baseline", r"no regression", r"final_errors"],
        "artifact_exists": [r"\btest -f\b", r"os\.path\.exists", r"os\.path\.isfile"],
        "non_empty_diff": [r"git diff.*grep -q", r"diff.*--name-only"],
    }

    def extract_verify_cmd(value):
        """Extract the VERIFY command string from a registry entry."""
        if isinstance(value, str):
            return value
        if isinstance(value, dict) and "verify" in value:
            return value["verify"]
        return None

    def find_state_file(skill, state_id):
        """Glob for .claude/skills/<dir>/state-<id>-*.md; fall back to
        .claude/patterns/ for shared terminal states (e.g. "99" → state-99-epilogue.md)."""
        SKILL_DIR_MAP = {
            "iterate-check": "iterate",
            "iterate-cross": "iterate",
            "iterate-cross-phase2": "iterate",
        }
        directory = SKILL_DIR_MAP.get(skill, skill)
        pattern = os.path.join(skills_dir, directory, f"state-{state_id}-*.md")
        matches = glob.glob(pattern)
        if not matches:
            patterns_pattern = os.path.join(patterns_dir, f"state-{state_id}-*.md")
            matches = glob.glob(patterns_pattern)
        return matches[0] if matches else None

    def extract_section(text, header):
        """Extract content between **HEADER:** and the next **...:** section header.
        Skips matches inside code fences to avoid false positives."""
        lines = text.split('\n')
        in_fence = False
        capturing = False
        result = []
        target = f'**{header}:**'
        for line in lines:
            stripped = line.strip()
            # Track code fences
            if stripped.startswith('```'):
                in_fence = not in_fence
                if capturing:
                    result.append(line)
                continue
            if in_fence:
                if capturing:
                    result.append(line)
                continue
            # Outside code fences: look for section headers
            if not capturing and stripped.startswith(target):
                capturing = True
                # Capture any text after the header on the same line
                after = stripped[len(target):].strip()
                if after:
                    result.append(after)
                continue
            if capturing:
                # Stop at the next STANDARD section header. Real section headers
                # (ACTIONS, VERIFY, POSTCONDITIONS, PRECONDITIONS, STATE TRACKING,
                # NEXT) always start at column 0 with **UPPERCASE. Indented or
                # camelcase `**bold**` inline prose (e.g. `   **Present fix...**`)
                # is bullet formatting inside the section, not a section header.
                if line.startswith('**') and re.match(r'^\*\*[A-Z][A-Z_ ]*?:?\*\*', line):
                    break
                result.append(line)
        return '\n'.join(result).strip()

    def extract_verify_from_file(text):
        """Extract VERIFY section content (both fenced and unfenced)."""
        # Find the VERIFY section
        verify_section = extract_section(text, "VERIFY")
        if not verify_section:
            return ""

        # Extract bash code fence content if present
        fence_match = re.search(r'```bash\s*\n(.*?)```', verify_section, re.DOTALL)
        if fence_match:
            return fence_match.group(1).strip()

        # Return the full section text (includes HTML comments, plain text)
        return verify_section

    def extract_artifacts_from_postconditions(postcond_text):
        """Extract artifact file references from POSTCONDITIONS that represent created/written artifacts.
        Skips read-only references, deletion references, and conditional prior-run references."""
        artifacts = set()
        # Patterns that indicate the line is NOT about creating an artifact
        skip_patterns = re.compile(
            r'(?:read|understood|has been read|deleted|cleaned|rm -f|'
            r'If .*exists from a prior run|available in.memory|in-memory|'
            r'Context digest)',
            re.IGNORECASE
        )
        for line in postcond_text.split('\n'):
            stripped = line.strip()
            if not stripped or skip_patterns.search(stripped):
                continue
            # .runs/something.json, .runs/something.md, .runs/something.jsonl, .runs/something.txt
            for m in re.finditer(r'\.runs/[\w\-/]+\.(?:json|md|jsonl|txt)\b', stripped):
                artifacts.add(m.group(0))
            # experiment/*.yaml — only if the line suggests creation/modification
            for m in re.finditer(r'experiment/[\w\-]+\.yaml', stripped):
                artifacts.add(m.group(0))
            # package.json — only if not read-only
            if 'package.json' in stripped:
                artifacts.add('package.json')
        return artifacts

    def has_skip_annotation(postcond_text):
        """Check if postconditions have the skip annotation."""
        return '<!-- enforced by agent behavior, not VERIFY gate -->' in postcond_text

    def normalize_verify(cmd):
        """Normalize a VERIFY command for comparison: strip echo, whitespace, comments."""
        if not cmd:
            return ""
        lines = []
        for line in cmd.split('\n'):
            stripped = line.strip()
            # Skip empty lines, echo-only lines, pure comments
            if not stripped:
                continue
            if stripped.startswith('echo ') or stripped == 'echo':
                continue
            if stripped.startswith('#'):
                continue
            if stripped.startswith('<!--'):
                continue
            lines.append(stripped)
        return '\n'.join(lines)

    def commands_diverge(file_verify, registry_verify):
        """Check if state file VERIFY and registry VERIFY have substantive differences."""
        norm_file = normalize_verify(file_verify)
        norm_reg = normalize_verify(registry_verify)

        if not norm_file and not norm_reg:
            return False

        # Both empty after normalization = no divergence
        if not norm_file or not norm_reg:
            # One is empty, one isn't — could be intentional (file has comments only)
            # Only flag if registry has real commands but file doesn't (or vice versa)
            if norm_reg and not norm_file:
                return True
            return False

        # Compare the substantive content
        return norm_file != norm_reg

    def check_declared_drift(skill, state_id, value, file_text):
        """Detect drift between declarative fields in state-registry.json and state-file prose.

        Declarations are ESCAPE HATCHES that tell cross-file consistency audits
        (e.g. /review Dimension A) that a pattern is intentional. They must stay in
        sync with state-file prose, or they become silent false-negatives.

        Checked fields:
          - allows_early_exit_when: must have matching phrase in ACTIONS
          - verify_semantics: must have matching regex marker in VERIFY
        """
        out = []
        if not isinstance(value, dict):
            return out

        actions_text = extract_section(file_text, "ACTIONS").lower()
        verify_text = (extract_verify_from_file(file_text) + " " + extract_section(file_text, "VERIFY")).lower()

        declared_exit = value.get("allows_early_exit_when")
        if declared_exit:
            phrases = [declared_exit.replace("_", " ")] + SYNONYMS.get(declared_exit, [])
            if not any(p.lower() in actions_text for p in phrases):
                out.append(
                    f"  [{skill}:{state_id}] allows_early_exit_when='{declared_exit}' "
                    f"but ACTIONS prose lacks matching phrase (tried: {phrases})"
                )

        declared_sem = value.get("verify_semantics")
        if declared_sem:
            pats = VERIFY_SEMANTIC_MARKERS.get(declared_sem, [])
            if pats and not any(re.search(p, verify_text) for p in pats):
                out.append(
                    f"  [{skill}:{state_id}] verify_semantics='{declared_sem}' "
                    f"but VERIFY lacks matching markers (expected one of: {pats})"
                )
        return out


    # -- CHECK-X1: forward early-exit discovery (#928 + #1043 gap closure) --
    # If ACTIONS prose describes an early-exit path with a TERMINAL verb, the
    # registry entry MUST declare allows_early_exit_when=<condition> -- otherwise
    # state-completion-gate.sh will block the legitimate branch (review.2e bug
    # class; resolve.7 is the third instance found during /solve Phase 1 scan).
    #
    # Regex explicitly excludes forward motion ("proceed to STATE N"), mode
    # branches ("use direct mode", "proceed silently"), and fallbacks.
    EARLY_EXIT_TRIGGER = re.compile(
        r'\bIf (?:ALL |no |zero |0 |none |the .*? is empty|there are no )'
        r'.{0,300}?'
        r'(?:exit loop|exit early|'
        r'advance state.{0,100}?TERMINAL|skill ends|'
        r'no PR created|terminate)\b',
        re.IGNORECASE | re.DOTALL
    )

    # -- CHECK-X2: baseline/parity semantics discovery (#928 gap closure) --
    # If the outer state VERIFY enforces a non-strict baseline/pre-fix comparison,
    # registry MUST declare verify_semantics=<name> -- otherwise VERIFY will
    # enforce strict zero instead of no-regression-from-baseline (review.4 bug
    # class).
    #
    # Regex is deliberately tight: matches only *outcome* prose ("final_errors <=
    # baseline", "no regression from baseline") that describes a state-level
    # exit invariant. Does NOT match per-iteration keep/revert phrases like
    # "if error count same or decreased -> keep the fix" which are internal
    # operations of a loop state, not the state's VERIFY semantics.
    BASELINE_PARITY_TRIGGER = re.compile(
        r'\b(?:'
        r'<=\s*(?:baseline|pre.?fix)'
        r'|no regression\s+(?:from|vs|against)\s+baseline'
        r'|final_errors\s*<=\s*baseline'
        r'|error count does not exceed baseline'
        r')',
        re.IGNORECASE
    )


    def check_x1_forward_early_exit(skill, state_id, value, file_text):
        """Flag state files whose ACTIONS contain early-exit TERMINAL prose but
        whose registry entry lacks allows_early_exit_when declaration."""
        out = []
        actions_text = extract_section(file_text, "ACTIONS")
        if not actions_text:
            return out
        declared = value.get("allows_early_exit_when") if isinstance(value, dict) else None
        m = EARLY_EXIT_TRIGGER.search(actions_text)
        if m and not declared:
            snippet = m.group(0).replace('\n', ' ')[:70]
            out.append(
                f"  [{skill}:{state_id}] ACTIONS contain early-exit TERMINAL prose "
                f"(matched: {snippet!r}) but registry lacks allows_early_exit_when"
            )
        return out


    def check_x2_baseline_parity(skill, state_id, value, file_text):
        """Flag state files whose ACTIONS describe a baseline/parity comparison
        but whose registry entry lacks verify_semantics declaration."""
        out = []
        actions_text = extract_section(file_text, "ACTIONS")
        if not actions_text:
            return out
        declared = value.get("verify_semantics") if isinstance(value, dict) else None
        m = BASELINE_PARITY_TRIGGER.search(actions_text)
        if m and not declared:
            snippet = m.group(0).replace('\n', ' ')[:70]
            out.append(
                f"  [{skill}:{state_id}] ACTIONS contain baseline/parity comparison "
                f"(matched: {snippet!r}) but registry lacks verify_semantics"
            )
        return out


    for skill, states in registry.items():
        if skill in SKIP_KEYS:
            continue
        if not isinstance(states, dict):
            continue

        for state_id, value in states.items():
            # Skip metadata keys
            if state_id.startswith('_'):
                continue

            verify_cmd = extract_verify_cmd(value)
            if verify_cmd is None:
                continue

            state_file = find_state_file(skill, state_id)
            if not state_file:
                print(f"WARNING: No state file for [{skill}:{state_id}]", file=sys.stderr)
                continue

            file_text = open(state_file).read()

            # --- Check 1: Artifact reference coverage ---
            postcond_text = extract_section(file_text, "POSTCONDITIONS")
            if postcond_text and not has_skip_annotation(postcond_text):
                artifacts = extract_artifacts_from_postconditions(postcond_text)
                for artifact in sorted(artifacts):
                    basename = os.path.basename(artifact)
                    # Check if artifact or its basename appears in registry VERIFY
                    if basename not in verify_cmd and artifact not in verify_cmd:
                        # Extract the postcondition line mentioning this artifact
                        context_line = ""
                        for line in postcond_text.split('\n'):
                            if artifact in line or basename in line:
                                context_line = line.strip().lstrip('- ')
                                break
                        uncovered.append(
                            f"  [{skill}:{state_id}] {artifact} -- postcondition: \"{context_line[:80]}\""
                        )

            # --- Check 2: State file / registry divergence ---
            # Skip divergence check for VERIFY=true entries (state files have prose justifications)
            file_verify = extract_verify_from_file(file_text)
            if verify_cmd.strip() != "true" and commands_diverge(file_verify, verify_cmd):
                file_summary = normalize_verify(file_verify)[:60].replace('\n', ' | ')
                reg_summary = normalize_verify(verify_cmd)[:60].replace('\n', ' | ')
                diverged.append(
                    f"  [{skill}:{state_id}] -- state file: {file_summary} | registry: {reg_summary}"
                )

            # --- Check 3: Unjustified true VERIFY ---
            if verify_cmd.strip() == "true":
                has_justification = (
                    '<!-- VERIFY=true:' in file_text or
                    '# VERIFY=true:' in file_text
                )
                if not has_justification:
                    unjustified_true.append(
                        f"  [{skill}:{state_id}] -- VERIFY is \"true\" but no justification comment found"
                    )

            # --- Check 4: Declared field / prose drift ---
            drift_declared.extend(check_declared_drift(skill, state_id, value, file_text))

            # --- Check 4b: Forward early-exit discovery (CHECK-X1) ---
            drift_declared.extend(check_x1_forward_early_exit(skill, state_id, value, file_text))

            # --- Check 4c: Baseline/parity semantics discovery (CHECK-X2) ---
            drift_declared.extend(check_x2_baseline_parity(skill, state_id, value, file_text))


    # ---------------------------------------------------------------------------
    # Check 5: Cross-file contradictions (rule-driven)
    # ---------------------------------------------------------------------------

    # ---------------------------------------------------------------------------
    # Helpers for per-section field_role_map check (#1024 follow-up)
    # ---------------------------------------------------------------------------

    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
    _PRAGMA_RE_TEMPLATE = (
        r"<!--\s*coherence-allow:\s*raw-{field}"
        r"(?:\s*\(([^)]*)\))?"
        r"(?:\s*scope=(\[[^\]]*\]))?"
        r"\s*(?:[—-]\s*(.*?))?\s*-->"
    )


    def _scan_headings(text):
        """Return [(line_num, level, heading_text)] for all markdown headings."""
        out = []
        for m in _HEADING_RE.finditer(text):
            line = text[: m.start()].count("\n") + 1
            out.append((line, len(m.group(1)), m.group(2).strip()))
        return out


    def _enclosing_block(headings, occurrence_line):
        """Return (containing, block_end_line_inclusive_or_None).

        Considered scope: H2/H3 only. H1 is the file title — not a semantic
        block boundary. H4+ is sub-content of the nearest H2/H3.

        `containing` is None when the occurrence precedes any H2/H3 heading;
        in that case the caller treats the extent as "preamble" (or whole
        file when no H2/H3 exists at all).
        """
        scoped = [(ln, lvl, txt) for ln, lvl, txt in headings if lvl in (2, 3)]
        containing = None
        containing_idx = -1
        for i, (ln, lvl, txt) in enumerate(scoped):
            if ln > occurrence_line:
                break
            containing = (ln, lvl, txt)
            containing_idx = i
        if containing is None:
            return None, None
        _, containing_lvl, _ = containing
        end = None
        for ln, lvl, _ in scoped[containing_idx + 1:]:
            if lvl <= containing_lvl:
                end = ln - 1
                break
        return containing, end


    def _parse_pragmas(text, field):
        """Return list of {line, qualifier, scope, raw, end_line} for pragmas."""
        out = []
        pat = re.compile(
            _PRAGMA_RE_TEMPLATE.format(field=re.escape(field)),
            re.DOTALL,
        )
        for m in pat.finditer(text):
            start_line = text[: m.start()].count("\n") + 1
            end_line = text[: m.end()].count("\n") + 1
            scope_raw = m.group(2)
            scope = None
            if scope_raw:
                try:
                    scope = json.loads(scope_raw)
                    if not (isinstance(scope, list)
                            and all(isinstance(x, str) for x in scope)):
                        scope = "MALFORMED"
                except Exception:
                    scope = "MALFORMED"
            out.append({
                "line": start_line,
                "end_line": end_line,
                "qualifier": m.group(1),
                "scope": scope,
                "raw": m.group(0),
            })
        return out


    def _normalize_heading(h):
        """Strip leading `#`+space prefix so `"## Step 3"` and `"Step 3"` match."""
        return re.sub(r"^#+\s+", "", h).strip()


    def check_field_role_map(rule):
        """Verify SET-semantic consumers of `field` either call the canonical
        function or declare a heading-scoped pragma covering the section.

        Rule shape:
          {
            "id": "<rule_id>",
            "type": "field_role_map",
            "field": "<field_name>",         # e.g. "golden_path"
            "canonical_function": "<name>",  # e.g. "derive_scope_pages"
            "consumers": ["<file>", ...]     # paths relative to repo root
          }

        Per-occurrence check (#1024 follow-up — catches mixed-semantic files):
          For each raw `<field>` occurrence outside a pragma comment, the
          enclosing ## / ### block must contain EITHER a
          `<!-- coherence-allow: raw-<field> ... scope=["## Heading", ...] -->`
          pragma whose scope list matches the block heading, OR a
          `<canonical>(` call in the same block.

          Legacy file-scope pragmas (no scope=[...]) still allow raw access
          anywhere in the file but emit a DEPRECATION WARN so templates
          can be migrated incrementally. Future versions will BLOCK.

          Any `scope=[...]` entry that does not match a heading currently
          present in the file is flagged immediately — catches renames.

        Forbidden patterns (UNCONDITIONAL — pragma cannot whitelist these):
          `len(... <field> ...)` and `set(... <field> ...)`
          Count-based access defeats the centralization purpose.
        """
        out = []
        canonical = rule.get("canonical_function", "")
        field = rule.get("field", "")
        rid = rule.get("id", "<unknown>")
        if not canonical or not field:
            out.append(
                f"  [{rid}] rule definition incomplete "
                f"(need canonical_function and field)"
            )
            return out

        forbidden = [
            re.compile(rf"\blen\s*\(\s*[^)]*\b{re.escape(field)}\b"),
            re.compile(rf"\bset\s*\(\s*[^)]*\b{re.escape(field)}\b"),
        ]
        occ_re = re.compile(rf"\b{re.escape(field)}\b")

        for consumer_path in rule.get("consumers", []):
            full = os.path.join(REPO_ROOT, consumer_path)
            if not os.path.isfile(full):
                out.append(f"  [{rid}] consumer not found on disk: {consumer_path}")
                continue
            text = open(full).read()
            lines = text.splitlines()

            # 1. Unconditional forbidden patterns (pragma cannot whitelist)
            for pat in forbidden:
                for m in pat.finditer(text):
                    line_num = text[: m.start()].count("\n") + 1
                    out.append(
                        f"  [{rid}] {consumer_path}:{line_num} forbidden "
                        f"count-based access: {m.group(0)!r} "
                        f"(pragma cannot whitelist this)"
                    )

            headings = _scan_headings(text)
            heading_texts_norm = {_normalize_heading(t) for _, _, t in headings}
            pragmas = _parse_pragmas(text, field)

            # 2. Validate scope=[...] integrity — every listed heading must
            # match a current heading (catches renames).
            for p in pragmas:
                if p["scope"] == "MALFORMED":
                    out.append(
                        f"  [{rid}] {consumer_path}:{p['line']} malformed "
                        f"scope=[...] JSON in pragma"
                    )
                elif isinstance(p["scope"], list):
                    for h in p["scope"]:
                        if _normalize_heading(h) not in heading_texts_norm:
                            out.append(
                                f"  [{rid}] {consumer_path}:{p['line']} "
                                f"pragma scope=[...] references heading "
                                f"not found in file: {h!r} — rename or "
                                f"remove. Current H2/H3 headings: "
                                f"{sorted(_normalize_heading(t) for _, lvl, t in headings if lvl in (2,3))}"
                            )

            has_legacy_file_scope_pragma = any(
                p["scope"] is None for p in pragmas
            )
            legacy_reported = False

            # 3. For each raw occurrence, check the enclosing block
            for m in occ_re.finditer(text):
                ln = text[: m.start()].count("\n") + 1

                # Skip occurrences inside pragma comments themselves
                in_pragma = any(
                    p["line"] <= ln <= p["end_line"] for p in pragmas
                )
                if in_pragma:
                    continue

                # Skip occurrences in markdown comments that are NOT pragmas
                # (conservative: a `<!-- ... golden_path ... -->` block is prose
                # about the field, not a consumption point).
                # Find enclosing `<!--` / `-->` on the same "HTML comment".
                # We scan backward from the occurrence to the nearest `<!--`
                # and forward to `-->` and check if they bracket the match.
                pre = text[: m.start()]
                last_open = pre.rfind("<!--")
                last_close_in_pre = pre.rfind("-->")
                if last_open != -1 and last_open > last_close_in_pre:
                    # We are inside an open HTML comment — check if it closes
                    # after the occurrence
                    rest = text[m.end():]
                    next_close = rest.find("-->")
                    if next_close != -1:
                        # Occurrence is inside <!-- ... --> and NOT one of
                        # our tracked pragmas — skip (prose, not consumption).
                        continue

                block, _ = _enclosing_block(headings, ln)
                scoped_hs = [(h_ln, h_lvl) for h_ln, h_lvl, _ in headings if h_lvl in (2, 3)]
                if block is None:
                    # Preamble: from file start to the first H2/H3 (exclusive),
                    # or whole file when no H2/H3 exists at all.
                    block_head_norm = None
                    block_head_display = "<preamble>"
                    block_start = 1
                    if scoped_hs:
                        block_end = scoped_hs[0][0] - 1
                    else:
                        block_end = len(lines)
                else:
                    block_head_line, block_head_lvl, block_head_text = block
                    block_head_norm = _normalize_heading(block_head_text)
                    block_head_display = block_head_text
                    block_start = block_head_line
                    block_end = None
                    for h_ln, h_lvl in scoped_hs:
                        if h_ln > block_head_line and h_lvl <= block_head_lvl:
                            block_end = h_ln - 1
                            break
                    if block_end is None:
                        block_end = len(lines)
                block_text = "\n".join(lines[block_start - 1:block_end])

                # Ancestor heading chain: when inside an H3, also check the
                # nearest ancestor H2. A pragma scoping ## Section X covers
                # every ### nested under it.
                ancestor_norms = set()
                if block is not None:
                    block_head_line, block_head_lvl, block_head_text = block
                    ancestor_norms.add(_normalize_heading(block_head_text))
                    if block_head_lvl == 3:
                        for h_ln, h_lvl, h_txt in headings:
                            if h_ln >= block_head_line:
                                break
                            if h_lvl == 2:
                                ancestor_norms.add(_normalize_heading(h_txt))
                            else:
                                # Reset ancestor when another H2 opens above
                                pass
                        # Narrow to the most recent H2 ancestor above this H3
                        latest_h2 = None
                        for h_ln, h_lvl, h_txt in headings:
                            if h_ln >= block_head_line:
                                break
                            if h_lvl == 2:
                                latest_h2 = _normalize_heading(h_txt)
                        # latest_h2 is already in ancestor_norms above; keep
                        # just the chain (block + its H2 ancestor) for
                        # deterministic matching.
                        ancestor_norms = {_normalize_heading(block_head_text)}
                        if latest_h2:
                            ancestor_norms.add(latest_h2)

                has_canonical_in_block = canonical in block_text

                pragma_covers = False
                for p in pragmas:
                    if isinstance(p["scope"], list):
                        normed = {_normalize_heading(h) for h in p["scope"]}
                        if ancestor_norms & normed:
                            pragma_covers = True
                            break

                if has_canonical_in_block or pragma_covers:
                    continue

                if has_legacy_file_scope_pragma:
                    # Legacy file-scope pragma — WARN once per file, still ALLOW
                    if not legacy_reported:
                        out.append(
                            f"  [{rid}] {consumer_path}:{ln} WARN: raw "
                            f"{field} under block {block_head_display!r} "
                            f"is currently allowed by a legacy file-scope "
                            f"pragma (no scope=[...]). Migrate the pragma "
                            f"to scope=[\"## Heading\", ...] syntax or "
                            f"switch the block to {canonical}(). Future "
                            f"versions will BLOCK."
                        )
                        legacy_reported = True
                    continue

                out.append(
                    f"  [{rid}] {consumer_path}:{ln} raw {field} in block "
                    f"{block_head_display!r} has neither {canonical}() "
                    f"call nor a scope-covering pragma. Add "
                    f"scope=[\"## {block_head_display}\"] to a pragma or "
                    f"switch the block to {canonical}()."
                )

        return out


    def check_discover_consumers(rule):
        """Grep-discover files mentioning `field` in a consumption context;
        report drift vs the authoritative consumers list in `against_rule`.

        Rule shape:
          {
            "id": "<rule_id>",
            "type": "discover_consumers",
            "field": "<field_name>",
            "against_rule": "<field_role_map rule id>",
            "path_excludes": ["<prefix>", ...],
            "consumption_patterns": ["<regex>", ...]
          }

        WARN-only: real violations are caught by the field_role_map rule.
        This check is purely for maintaining the consumers list over time.
        """
        out = []
        rid = rule.get("id", "<unknown>")
        field = rule.get("field", "")
        against = rule.get("against_rule")
        excludes = rule.get("path_excludes", [])
        patterns_raw = rule.get("consumption_patterns", [])
        if not field or not against or not patterns_raw:
            out.append(
                f"  [{rid}] rule definition incomplete "
                f"(need field, against_rule, consumption_patterns)"
            )
            return out
        try:
            patterns = [re.compile(p) for p in patterns_raw]
        except re.error as exc:
            out.append(f"  [{rid}] invalid consumption_patterns regex: {exc}")
            return out

        authoritative = set()
        try:
            with open(RULES_PATH) as f:
                for r in json.load(f).get("rules", []):
                    if r.get("id") == against:
                        authoritative = set(r.get("consumers", []))
                        break
        except (OSError, json.JSONDecodeError) as exc:
            out.append(
                f"  [{rid}] failed to read authoritative list from "
                f"{RULES_PATH}: {exc}"
            )
            return out

        def _excluded(rel):
            rel_posix = rel.replace(os.sep, "/")
            for ex in excludes:
                ex_posix = ex.replace(os.sep, "/").rstrip("/")
                if rel_posix == ex_posix or rel_posix.startswith(ex_posix + "/"):
                    return True
            return False

        search_root = os.path.join(REPO_ROOT, ".claude")
        allowed_ext = (".md", ".py", ".sh", ".ts", ".tsx", ".json")
        field_word_re = re.compile(rf"\b{re.escape(field)}\b")
        found = set()
        has_any_reference = set()
        for root, dirs, files in os.walk(search_root):
            # Prune excluded subtrees
            pruned = []
            for d in list(dirs):
                rel_d = os.path.relpath(os.path.join(root, d), REPO_ROOT)
                if _excluded(rel_d):
                    pruned.append(d)
            for d in pruned:
                dirs.remove(d)
            for fn in files:
                if not fn.endswith(allowed_ext):
                    continue
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, REPO_ROOT)
                if _excluded(rel):
                    continue
                try:
                    with open(full, encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                except OSError:
                    continue
                if field_word_re.search(text):
                    has_any_reference.add(rel)
                if any(p.search(text) for p in patterns):
                    found.add(rel)

        missing = found - authoritative
        # Intentionally do NOT flag "stale" entries — a consumer that has
        # been fully migrated to the canonical function may legitimately
        # have zero bare-word references. Keeping it in the consumers
        # list serves as regression vigilance: if a future author
        # reintroduces raw access, the field_role_map rule fires. We
        # surface drift only in one direction (grep-found files that are
        # NOT listed) to avoid churning the consumers list on migration.
        stale = set()
        for m in sorted(missing):
            out.append(
                f"  [{rid}] WARN: {m} contains consumption-pattern for "
                f"{field!r} but is not listed in {against!r} consumers. "
                f"Either add it to the consumers list or audit whether "
                f"the read is a drift violation."
            )
        for s in sorted(stale):
            out.append(
                f"  [{rid}] WARN: {s} is listed in {against!r} consumers "
                f"but no longer matches consumption patterns for "
                f"{field!r}. Remove from consumers list (stale entry)."
            )
        return out


    # Patterns that indicate an artifact reference is NOT a real consumption
    # (used to filter false positives in artifact_lifecycle check). Mirrors the
    # existing `extract_artifacts_from_postconditions` skip_patterns precedent.
    _ARTIFACT_SKIP_PATTERNS = re.compile(
        r"(?:not\s+os\.path\.exists|"
        r"not\s+os\.path\.isfile|"
        r"deleted|cleaned|rm\s+-f|"
        r"if\s+.*exists\s+from\s+a\s+prior\s+run)",
        re.IGNORECASE,
    )


    def check_artifact_lifecycle(rule):
        """Verify artifact producer/consumer ordering across states in a skill.

        Rule shape:
          {
            "id": "<rule_id>",
            "type": "artifact_lifecycle",
            "skill": "<skill_name>"     # which skill's states to scan
          }

        For the named skill: each state can declare optional `produces: [...]`
        and `do_not_modify: [...]` arrays in state-registry.json. The check:
          (a) every artifact appearing in a state's VERIFY (regex-extracted)
              MUST be in some upstream state's `produces` declaration, OR
              NOT be `do_not_modify` flagged anywhere upstream
          (b) `do_not_modify[X]` declared in state B + `produces[X]` declared
              in any state after B = DO_NOT_MODIFY_VIOLATION

        Conservative: only fires when both `produces` and `do_not_modify` are
        explicitly declared. Pure prose (e.g. "do not write to X" in ACTIONS)
        is intentionally NOT parsed — too brittle.
        """
        out = []
        skill = rule.get("skill", "")
        rid = rule.get("id", "<unknown>")
        if not skill or skill not in registry or not isinstance(registry[skill], dict):
            return out

        states = registry[skill]
        # Build state ordering from registry key order (insertion order is preserved
        # in Python 3.7+ JSON load and reflects the canonical skill flow).
        ordered_states = [s for s in states if not s.startswith("_") and isinstance(states[s], (dict, str))]
        state_position = {s: i for i, s in enumerate(ordered_states)}

        produces_at = {}     # artifact -> earliest state position that produces it
        forbids_at = {}      # artifact -> earliest state position that forbids it

        for sid in ordered_states:
            val = states[sid]
            if not isinstance(val, dict):
                continue
            for a in (val.get("produces") or []):
                produces_at.setdefault(a, []).append(state_position[sid])
            for a in (val.get("do_not_modify") or []):
                forbids_at.setdefault(a, []).append(state_position[sid])

        # Check (a): VERIFY-referenced artifacts must have a producer upstream
        artifact_re = re.compile(r"\.runs/[a-z0-9-]+\.(?:json|md|jsonl|txt|flag)")
        for sid in ordered_states:
            val = states[sid]
            verify_cmd = extract_verify_cmd(val)
            if not verify_cmd or verify_cmd.strip() == "true":
                continue
            if _ARTIFACT_SKIP_PATTERNS.search(verify_cmd):
                # Verify contains negated/skip patterns; conservative — skip
                continue
            for m in artifact_re.finditer(verify_cmd):
                artifact = m.group(0)
                sid_pos = state_position[sid]
                producer_positions = produces_at.get(artifact, [])
                if producer_positions and not any(p <= sid_pos for p in producer_positions):
                    out.append(
                        f"  [{rid}] {skill}:{sid} VERIFY references {artifact} "
                        f"but no upstream state declares produces"
                    )

        # Check (b): do_not_modify[X] cannot precede produces[X]
        for artifact, forbid_positions in forbids_at.items():
            producer_positions = produces_at.get(artifact, [])
            for fp in forbid_positions:
                for pp in producer_positions:
                    if fp < pp:
                        forbid_state = ordered_states[fp]
                        produce_state = ordered_states[pp]
                        out.append(
                            f"  [{rid}] {skill}:{forbid_state} do_not_modify includes {artifact} "
                            f"but {skill}:{produce_state} (later) declares produces"
                        )
        return out


    def check_artifact_transience(rule):
        """Validate `lifecycle: transient-*` declarations against actual deletion sources.

        Rule shape:
          {
            "id": "<rule_id>",
            "type": "artifact_transience",
            "skill": "<skill_name>",
            "init_script": "<optional path; default .claude/scripts/lifecycle-init.sh>"
          }

        For each entry under registry[skill] with `lifecycle != "durable"`:
          (a) `artifact` field MUST be declared.
          (b) `lifecycle == "transient-cross-skill"` MUST match a path in
              lifecycle-init.sh STALE_ARTIFACTS / DELIVERY_ARTIFACTS (or
              fall under a cleaned directory like .runs/agent-traces/).
          (c) `lifecycle == "transient-intra-skill"` MUST match a state-*.md
              file (in this same skill) whose ACTIONS contain a `rm -f`/`Delete`
              for the path.

        Coexists with check_artifact_lifecycle (orthogonal — flow vs durability axes).
        Closes #1162 recurrence-prevention.
        """
        out = []
        skill = rule.get("skill", "")
        if not skill or skill not in registry:
            return out
        skill_states = registry[skill]
        if not isinstance(skill_states, dict):
            return out

        init_script = rule.get("init_script", os.path.join(REPO_ROOT, ".claude/scripts/lifecycle-init.sh"))
        try:
            init_text = open(init_script).read()
        except OSError:
            return [_emit_finding(rule, f"cannot read {init_script}")]

        # Cross-skill paths (file paths under STALE_ARTIFACTS / DELIVERY_ARTIFACTS)
        cross_skill_paths = set()
        for m in re.finditer(r'"\$PROJECT_DIR(/\.runs/[^"]+)"', init_text):
            cross_skill_paths.add(m.group(1).lstrip("/"))
        # Cleaned directories (paths ending in /)
        cleaned_dirs = {p for p in cross_skill_paths if p.endswith("/")}

        # Same-skill deletions: scan only state files of THIS skill plus shared patterns
        intra_paths = set()
        skill_state_files = sorted(glob.glob(os.path.join(skills_dir, skill, "state-*.md")))
        pattern_files = [os.path.join(patterns_dir, "state-99-epilogue.md")]
        for sf in skill_state_files + pattern_files:
            if not os.path.isfile(sf):
                continue
            try:
                text = open(sf).read()
            except OSError:
                continue
            # bash code fences
            for m in re.finditer(r"```bash\s*\n(.*?)```", text, re.DOTALL):
                for m2 in re.finditer(
                    r"(?:rm\s+-[rfRF]+\s+|os\.remove\(['\"]|os\.unlink\(['\"])"
                    r"([^\s'\")]*\.runs/[A-Za-z0-9_./-]+)",
                    m.group(1),
                ):
                    a = m2.group(1).rstrip("'\")").lstrip("'\"")
                    if a.startswith("$PROJECT_DIR/"):
                        a = a[len("$PROJECT_DIR/"):]
                    if a.startswith(".runs/"):
                        intra_paths.add(a)
            # imperative prose
            for m in re.finditer(r"(?m)^\s*[-*]\s+Delete\s+`(\.runs/[A-Za-z0-9_./-]+)`", text):
                intra_paths.add(m.group(1))

        # Pre-compute the set of paths each VERIFY command references — needed
        # for both directions of the check.
        artifact_re = re.compile(r"\.runs/[A-Za-z0-9_./-]+")

        def is_known_transient(path):
            """Return True iff path matches a known cross-skill OR intra-skill
            deletion source. Used to detect mis-declared durable entries."""
            if path in cross_skill_paths:
                return True
            if any(path.startswith(d) for d in cleaned_dirs):
                return True
            if path in intra_paths:
                return True
            return False

        for sid, val in skill_states.items():
            if sid.startswith("_"):
                continue
            # --- Forward check: declared transient must match a deletion source ---
            if isinstance(val, dict):
                lc = val.get("lifecycle", "durable")
                artifact = val.get("artifact")
                if lc != "durable":
                    if not artifact:
                        out.append(_emit_finding(rule, f"{skill}:{sid} declares lifecycle={lc} but no `artifact` declared"))
                        continue
                    if lc == "transient-cross-skill":
                        if artifact not in cross_skill_paths and not any(artifact.startswith(d) for d in cleaned_dirs):
                            out.append(_emit_finding(rule,
                                f"{skill}:{sid} declares transient-cross-skill but {artifact} is not in "
                                f"lifecycle-init.sh STALE_ARTIFACTS / DELIVERY_ARTIFACTS"))
                    elif lc == "transient-intra-skill":
                        if artifact not in intra_paths:
                            out.append(_emit_finding(rule,
                                f"{skill}:{sid} declares transient-intra-skill but no state-*.md "
                                f"of skill={skill} deletes {artifact} (scanned bash code fences and "
                                f"imperative `- Delete \\`{artifact}\\`` prose)"))
                    else:
                        out.append(_emit_finding(rule, f"{skill}:{sid} unknown lifecycle value '{lc}'"))
                    continue  # transient entries: forward check only

            # --- Inverse check: durable entry's VERIFY must NOT reference a known transient path ---
            # Catches entries that LOOK transient (their VERIFY checks an
            # init-cleaned or intra-skill-deleted path) but were declared
            # durable. This is the most common authoring error: someone adds
            # a new state without thinking about lifecycle.
            verify_cmd = extract_verify_cmd(val)
            if not verify_cmd or verify_cmd.strip() == "true":
                continue
            for m in artifact_re.finditer(verify_cmd):
                referenced = m.group(0)
                if is_known_transient(referenced):
                    out.append(_emit_finding(rule,
                        f"{skill}:{sid} is declared durable but its VERIFY references "
                        f"{referenced} which is a known transient artifact "
                        f"(in lifecycle-init STALE_ARTIFACTS/DELIVERY_ARTIFACTS or "
                        f"deleted by a state-*.md of skill={skill}). Either declare "
                        f"the entry as transient-cross-skill / transient-intra-skill, "
                        f"or change the VERIFY command to not depend on the path."))
                    break  # one finding per state is enough
        return out


    def check_executor_enforcement(rule):
        """Three-way mapping check for lead-only artifacts.

        Rule shape:
          {
            "id": "<rule_id>",
            "type": "executor_enforcement",
            "manifest_path": ".claude/patterns/lead-only-artifacts.json",
            "hooks_dir": "<optional path; default .claude/hooks>",
            "agents_glob": "<optional glob; default .claude/agents/*.md>"
          }

        For each artifact in lead-only-artifacts.json:
          (a) Hook coverage: the manifest_path string OR the basename appears in
              at least one PreToolUse hook script (lead-deliverable-gate.sh /
              retrospective-content-gate.sh).
          (b) Schema coverage: the artifact's `schema_source` file declares the
              `executor_field` name (substring match).
          (c) Negative-deliverable coverage: NO file in agents_glob lists the
              artifact path as a deliverable. Exception: an agent .md may mention
              the path if it ALSO contains the explicit phrase "Evidence collection
              only" or "lead writes" (signaling it's documenting the lead-only
              constraint, not delegating).

        Closes #1152 recurrence-prevention.
        """
        out = []
        manifest_path = rule.get("manifest_path", os.path.join(REPO_ROOT, ".claude/patterns/lead-only-artifacts.json"))
        hooks_dir = rule.get("hooks_dir", os.path.join(REPO_ROOT, ".claude/hooks"))
        agents_glob = rule.get("agents_glob", os.path.join(REPO_ROOT, ".claude/agents/*.md"))

        try:
            manifest = json.load(open(manifest_path))
        except OSError as e:
            return [_emit_finding(rule, f"cannot read manifest {manifest_path}: {e}")]
        except json.JSONDecodeError as e:
            return [_emit_finding(rule, f"manifest {manifest_path} is not valid JSON: {e}")]

        # Read all hook contents (single read for efficiency)
        hook_text = ""
        if os.path.isdir(hooks_dir):
            for h in sorted(os.listdir(hooks_dir)):
                hp = os.path.join(hooks_dir, h)
                if os.path.isfile(hp):
                    try:
                        hook_text += open(hp).read() + "\n"
                    except OSError:
                        continue

        manifest_basename = os.path.basename(manifest_path)
        # (a) hook coverage: manifest reference appears anywhere in hooks
        if manifest_path not in hook_text and manifest_basename not in hook_text:
            out.append(_emit_finding(rule,
                f"no PreToolUse hook references the manifest "
                f"({manifest_path}); lead-only enforcement is not wired"))

        # Read all agent .md files once
        agent_files = sorted(glob.glob(agents_glob))
        agent_text_map = {}
        for af in agent_files:
            try:
                agent_text_map[af] = open(af).read()
            except OSError:
                continue

        for entry in manifest.get("artifacts", []):
            path = entry.get("path", "")
            executor_field = entry.get("executor_field", "")
            schema_source = entry.get("schema_source", "")
            if not path or not executor_field or not schema_source:
                out.append(_emit_finding(rule,
                    f"manifest entry incomplete: {entry} (need path, executor_field, schema_source)"))
                continue

            # (b) schema coverage
            schema_abs = schema_source if os.path.isabs(schema_source) else os.path.join(REPO_ROOT, schema_source)
            if os.path.isfile(schema_abs):
                try:
                    schema_text = open(schema_abs).read()
                except OSError:
                    schema_text = ""
                if executor_field not in schema_text:
                    out.append(_emit_finding(rule,
                        f"{schema_source} does not declare executor_field "
                        f"'{executor_field}' for artifact {path}"))
            else:
                out.append(_emit_finding(rule,
                    f"schema_source {schema_source} does not exist for artifact {path}"))

            # (c) negative-deliverable coverage
            for af, txt in agent_text_map.items():
                if path not in txt:
                    continue
                # Allow files that explicitly document the lead-only constraint
                if "Evidence collection only" in txt or "lead writes" in txt or "lead must execute" in txt:
                    continue
                out.append(_emit_finding(rule,
                    f"{os.path.relpath(af, REPO_ROOT)} mentions lead-only artifact "
                    f"{path} (negative-deliverable violation; if this agent is meant to "
                    f"READ the file from prior runs, add an explicit 'lead writes' or "
                    f"'Evidence collection only' caveat to the agent prose)"))
        return out


    def check_gate_artifact_identity(rule):
        """GRAIM v2 C1+C2 lint: VERIFY blocks reading enforced_artifacts must assert
        {skill, run_id} match against active context. Warn-only by default; per-artifact
        severity flip happens via enforced_artifacts allowlist growth in Slice 3.

        Rule shape:
          {
            "id": "<rule_id>",
            "type": "gate_artifact_identity",
            "manifest_path": ".claude/patterns/gate-readable-artifacts-canonical.json",
            "enforced_artifacts": [".runs/observation-enforcement.json", ...],
            "registry_path": "<optional path; default .claude/patterns/state-registry.json>"
          }

        Walks every VERIFY string in state-registry.json. For each enforced artifact
        whose path appears in a VERIFY block, the block MUST also assert
        d.get('skill') == active_skill AND d.get('run_id') == active_run_id.
        """
        out = []
        enforced = set(rule.get("enforced_artifacts", []))
        if not enforced:
            return out  # nothing to enforce yet — allowlist is empty

        reg_path = rule.get("registry_path", os.path.join(REPO_ROOT, ".claude/patterns/state-registry.json"))
        reg_abs = reg_path if os.path.isabs(reg_path) else os.path.join(REPO_ROOT, reg_path)
        if not os.path.isfile(reg_abs):
            return [_emit_finding(rule, f"registry not found at {reg_path}")]
        try:
            reg = json.load(open(reg_abs))
        except (OSError, json.JSONDecodeError) as e:
            return [_emit_finding(rule, f"registry unreadable: {e}")]

        # Walk every VERIFY string in the registry. Mirrors check_artifact_transience:
        # registry top-level is dict-of-skills; each skill's children are state entries,
        # and a state entry is EITHER a bare string (legacy VERIFY) OR a dict with a
        # `verify` key. Sibling fields like `artifact` / `lifecycle` are NOT verify
        # strings and must not be treated as such.
        verify_strings = []
        for skill_name, skill_node in reg.items():
            if not isinstance(skill_node, dict):
                continue
            for state_id, state_val in skill_node.items():
                if isinstance(state_val, str):
                    verify_strings.append((f"{skill_name}.{state_id}", state_val))
                elif isinstance(state_val, dict):
                    v = state_val.get("verify")
                    if isinstance(v, str):
                        verify_strings.append((f"{skill_name}.{state_id}.verify", v))

        for state_path, verify_str in verify_strings:
            for art in enforced:
                if art not in verify_str:
                    continue
                # Identity assertion checks: must compare d.get('skill')/d.get('run_id')
                # against active_skill/active_run_id.
                has_skill_check = (
                    ("d.get('skill')" in verify_str or 'd.get("skill")' in verify_str)
                    and "active_skill" in verify_str
                )
                has_run_id_check = (
                    ("d.get('run_id')" in verify_str or 'd.get("run_id")' in verify_str)
                    and "active_run_id" in verify_str
                )
                if not (has_skill_check and has_run_id_check):
                    out.append(_emit_finding(rule,
                        f"VERIFY at registry.{state_path} reads {art} but lacks "
                        f"skill/run_id identity assertion (GRAIM v2 C2 violation)"))
        return out


    def check_boundary_kind_required(rule):
        """GRAIM v2 C3 lint: declared fast-path branches must gate on
        boundary_kind == diff. Empty-signal fast-paths must require explicit opt-in.

        Rule shape:
          {
            "id": "<rule_id>",
            "type": "boundary_kind_required",
            "enforced_artifacts": [".runs/agent-traces/design-critic-*.json", ...],
            "agent_files_glob": "<optional; default .claude/agents/*.md>",
            "skill_files_glob": "<optional; default .claude/skills/**/*.md>"
          }

        For each enforced boundary-emitting artifact path, scan agent + skill files
        for fast-path heuristics (the words "fast-path"/"fast_path" near the path)
        without `boundary_kind` gating.
        """
        out = []
        enforced = set(rule.get("enforced_artifacts", []))
        if not enforced:
            return out

        skill_glob = rule.get("skill_files_glob", os.path.join(REPO_ROOT, ".claude/skills/**/*.md"))
        agent_glob = rule.get("agent_files_glob", os.path.join(REPO_ROOT, ".claude/agents/*.md"))
        # Resolve relative globs against REPO_ROOT
        if not os.path.isabs(skill_glob):
            skill_glob = os.path.join(REPO_ROOT, skill_glob)
        if not os.path.isabs(agent_glob):
            agent_glob = os.path.join(REPO_ROOT, agent_glob)

        candidate_files = sorted(glob.glob(skill_glob, recursive=True)) + sorted(glob.glob(agent_glob))
        for sf in candidate_files:
            try:
                content = open(sf).read()
            except OSError:
                continue
            lower_content = content.lower()
            mentions_fast_path = ("fast-path" in lower_content or "fast_path" in lower_content)
            if not mentions_fast_path:
                continue
            for art in enforced:
                if art in content and "boundary_kind" not in content:
                    out.append(_emit_finding(rule,
                        f"{os.path.relpath(sf, REPO_ROOT)} mentions {art} fast-path "
                        f"but does not gate on boundary_kind == diff (GRAIM v2 C3 violation)"))
        return out


    def check_gate_artifact_discovery(rule):
        """GRAIM v2 promotion guard: warn-only — find .runs/*.json paths gate-read by
        VERIFY/hooks that are NOT declared in the canonical manifest. Catches the
        case where a telemetry artifact silently becomes gate-readable.

        Rule shape:
          {
            "id": "<rule_id>",
            "type": "gate_artifact_discovery",
            "manifest_path": ".claude/patterns/gate-readable-artifacts-canonical.json",
            "registry_path": "<optional; default .claude/patterns/state-registry.json>",
            "hooks_glob": "<optional; default .claude/hooks/*.sh>"
          }
        """
        out = []
        manifest_path = rule.get("manifest_path", os.path.join(REPO_ROOT, ".claude/patterns/gate-readable-artifacts-canonical.json"))
        registry_path = rule.get("registry_path", os.path.join(REPO_ROOT, ".claude/patterns/state-registry.json"))
        hooks_glob = rule.get("hooks_glob", os.path.join(REPO_ROOT, ".claude/hooks/*.sh"))

        if not os.path.isabs(manifest_path):
            manifest_path = os.path.join(REPO_ROOT, manifest_path)
        if not os.path.isabs(registry_path):
            registry_path = os.path.join(REPO_ROOT, registry_path)
        if not os.path.isabs(hooks_glob):
            hooks_glob = os.path.join(REPO_ROOT, hooks_glob)

        if not os.path.isfile(manifest_path):
            return out  # silent no-op: manifest absent means GRAIM not yet present
        try:
            manifest = json.load(open(manifest_path))
        except (OSError, json.JSONDecodeError):
            return out

        declared = {a.get("path", "") for a in manifest.get("artifacts", []) if a.get("path")}

        # Discover .runs/*.json paths in VERIFY blocks (raw text scan over registry)
        discovered = set()
        artifact_re = re.compile(r"\.runs/[a-zA-Z0-9_./-]+\.json(?![a-zA-Z0-9])")
        if os.path.isfile(registry_path):
            try:
                reg_text = open(registry_path).read()
                for m in artifact_re.finditer(reg_text):
                    discovered.add(m.group(0))
            except OSError:
                pass

        # Discover .runs/*.json paths in hooks
        for hook in sorted(glob.glob(hooks_glob)):
            try:
                text = open(hook).read()
                for m in artifact_re.finditer(text):
                    discovered.add(m.group(0))
            except OSError:
                continue

        # Promotion candidates: discovered but not declared
        promotion_candidates = discovered - declared
        for art in sorted(promotion_candidates):
            out.append(_emit_finding(rule,
                f"{art} is gate-read (in VERIFY or hook) but not declared in "
                f"GRAIM canonical manifest — promotion regression risk"))
        return out


    def check_gate_evidence_escape(rule):
        """EARC slice 1: every gate listed in gate-inventory.json with
        earc_subpattern in {gate-side, writer-side} must offer a documented
        evidence escape — either an inline reference to attestation/repair-
        evidence/earc-attestation, OR an entry in `state-registry.json` with
        a non-null `repair_evidence` block.

        Rule shape:
          {
            "id": "earc-gate-evidence-escape",
            "type": "gate_evidence_escape",
            "severity": "warn" | "block",
            "inventory_path": ".claude/patterns/gate-inventory.json",
            "registry_path": ".claude/patterns/state-registry.json"
          }

        The rule ships in WARN severity (slice 1) and flips to BLOCK in slice 4
        after a one-week soak with zero new findings. Closes #1182 and #1189
        recurrence-prevention dimension.
        """
        out = []
        inv_path = rule.get("inventory_path", ".claude/patterns/gate-inventory.json")
        reg_path = rule.get("registry_path", ".claude/patterns/state-registry.json")
        inv_abs = inv_path if os.path.isabs(inv_path) else os.path.join(REPO_ROOT, inv_path)
        reg_abs = reg_path if os.path.isabs(reg_path) else os.path.join(REPO_ROOT, reg_path)

        if not os.path.isfile(inv_abs):
            return [_emit_finding(rule,
                f"gate-inventory.json missing at {inv_path} — "
                f"EARC coverage cannot be verified. Slice -1 should land before this rule activates.")]
        try:
            inv = json.load(open(inv_abs))
        except (OSError, json.JSONDecodeError) as e:
            return [_emit_finding(rule, f"cannot read inventory: {e}")]

        # Optional registry — when present, gates may declare their evidence
        # channel via state-registry.repair_evidence (Slice 2 / Slice 3).
        registry_repair_paths = set()
        if os.path.isfile(reg_abs):
            try:
                reg = json.load(open(reg_abs))
                for skill_name, states in reg.items():
                    if not isinstance(states, dict):
                        continue
                    for state_id, state_def in states.items():
                        if not isinstance(state_def, dict):
                            continue
                        re_block = state_def.get("repair_evidence")
                        if isinstance(re_block, dict) and re_block.get("writer"):
                            registry_repair_paths.add(re_block.get("writer"))
            except (OSError, json.JSONDecodeError):
                pass

        for gate in inv.get("gates", []):
            subpattern = gate.get("earc_subpattern")
            if subpattern not in ("gate-side", "writer-side"):
                continue
            gate_path = gate.get("path", "")
            if not gate_path:
                continue
            gate_abs = gate_path if os.path.isabs(gate_path) else os.path.join(REPO_ROOT, gate_path)
            if not os.path.isfile(gate_abs):
                # Inventory entry refers to non-existent file — separate
                # invariant; skip rather than double-warn.
                continue
            try:
                content = open(gate_abs).read().lower()
            except OSError:
                continue
            # Heuristic match: any of "attestation", "earc", "repair_evidence",
            # "lead_evidence_source", "lead_transcribed", or "evidence_validated"
            # signals the gate is aware of the EARC contract. Writers covered
            # in the registry's repair_evidence block are also implicitly OK.
            inline_signals = (
                "attestation" in content or "earc" in content
                or "repair_evidence" in content or "lead_evidence_source" in content
                or "lead_transcribed" in content or "evidence_validated" in content
            )
            registered = gate_path in registry_repair_paths
            if not (inline_signals or registered):
                out.append(_emit_finding(rule,
                    f"gate {gate_path} (earc_subpattern={subpattern!r}) lacks "
                    f"an evidence-escape branch and is not declared in any "
                    f"state-registry repair_evidence block. Either document "
                    f"the escape inline (mention attestation/EARC/lead_evidence_source) "
                    f"or wire it via state-registry.repair_evidence."))
        return out


    # ---------------------------------------------------------------------------
    # AOC v1 rule dispatchers (R1/R2/R3)
    # ---------------------------------------------------------------------------

    def _emit_finding(rule, message):
        """Emit a finding string tagged with rule id + type so downstream
        exit-logic can partition by rule type for --strict-aoc."""
        rid = rule.get("id", "<unknown>")
        rtype = rule.get("type", "<unknown>")
        sev = rule.get("severity", "block")
        doc = rule.get("convention_doc")
        doc_suffix = f" (see {doc})" if doc else ""
        return f"  [{rid}] ({rtype}/{sev}) {message}{doc_suffix}"


    def check_verdict_vocab_consistency(rule):
        """AOC v1 R1: agent definitions must emit only verdicts/results declared
        in verdict_agents_schema, and evaluate-hard-gate-predicates.py predicates
        must reference only declared verdict values."""
        findings = []
        rid = rule.get("id", "<unknown>")

        reg_path = os.path.join(REPO_ROOT, rule.get("registry_path", ""))
        if not os.path.isfile(reg_path):
            findings.append(_emit_finding(rule, f"registry file missing: {reg_path}"))
            return findings
        try:
            reg = json.load(open(reg_path))
        except (OSError, json.JSONDecodeError) as e:
            findings.append(_emit_finding(rule, f"cannot read registry: {e}"))
            return findings

        schema = reg.get("verdict_agents_schema", {})
        if not schema:
            findings.append(_emit_finding(rule, "verdict_agents_schema missing from registry"))
            return findings

        # Build a union of all declared verdicts/results across agents.
        all_verdicts = set()
        all_results = set()
        for agent_name, spec in schema.items():
            for v in spec.get("allowed_verdicts", []):
                if v is not None:
                    all_verdicts.add(v)
            for r in spec.get("allowed_results", []):
                if r is not None:
                    all_results.add(r)

        # Core verdict vocabulary is fixed at 4 values per AOC v1.
        AOC_CORE_VERDICTS = {"pass", "fail", "blocked", "unresolved"}
        for v in all_verdicts:
            if v not in AOC_CORE_VERDICTS:
                findings.append(_emit_finding(
                    rule,
                    f"verdict_agents_schema contains non-AVS-v1 verdict: {v!r}. "
                    f"Allowed core verdicts are {sorted(AOC_CORE_VERDICTS)}."
                ))

        # Scan predicate file for verdict literals and confirm they are in the
        # core vocabulary (predicates should never reference legacy verdicts).
        pred_path = os.path.join(REPO_ROOT, rule.get("predicate_file", ""))
        if os.path.isfile(pred_path):
            try:
                pred_content = open(pred_path).read()
            except OSError:
                pred_content = ""
            # Find all double-quoted or single-quoted strings compared to t.get('verdict')
            # Heuristic: look for patterns like: t.get('verdict') == 'VALUE' or 'VALUE' in (...)
            verdict_literal_re = re.compile(
                r"t\.get\(['\"]verdict['\"]\)\s*==?\s*['\"]([a-zA-Z_\-]+)['\"]"
            )
            tuple_literal_re = re.compile(
                r"t\.get\(['\"]verdict['\"]\)\s+in\s*\(([^)]*)\)"
            )
            for m in verdict_literal_re.finditer(pred_content):
                lit = m.group(1)
                if lit not in AOC_CORE_VERDICTS and lit not in all_verdicts:
                    findings.append(_emit_finding(
                        rule,
                        f"{rule.get('predicate_file')} references non-registry verdict {lit!r}"
                    ))
            for m in tuple_literal_re.finditer(pred_content):
                tuple_body = m.group(1)
                for lit_m in re.finditer(r"['\"]([a-zA-Z_\-]+)['\"]", tuple_body):
                    lit = lit_m.group(1)
                    if lit not in AOC_CORE_VERDICTS and lit not in all_verdicts:
                        findings.append(_emit_finding(
                            rule,
                            f"{rule.get('predicate_file')} references non-registry verdict {lit!r}"
                        ))

        # Scan agent files (under agent_files_glob) for verdict values emitted.
        # We look for `"verdict":"<value>"` patterns; values like `<verdict>`
        # or `<pass|fail>` are templates and excluded.
        agent_glob = rule.get("agent_files_glob", "")
        if agent_glob:
            abs_glob = os.path.join(REPO_ROOT, agent_glob)
            verdict_agents = set(schema.keys())
            for agent_file in sorted(glob.glob(abs_glob)):
                agent_base = os.path.basename(agent_file).replace(".md", "")
                if agent_base not in verdict_agents:
                    continue  # Only enforce the declared 17 verdict_agents.
                try:
                    content = open(agent_file).read()
                except OSError:
                    continue
                spec = schema.get(agent_base, {})
                allowed_v = set(spec.get("allowed_verdicts", []))
                # Detect `"verdict":"<literal>"` (legacy uppercase, multi-word, or unknown-value emissions).
                # Values starting with `<` are template placeholders (e.g. <pass|fail>, <verdict>) — skip.
                # Values containing `|` alone are template alternation — skip.
                for m in re.finditer(r'"verdict"\s*:\s*"([^"<>]+)"', content):
                    lit = m.group(1).strip()
                    if not lit:
                        continue
                    if "|" in lit:
                        continue
                    # Normalize casing
                    lit_norm = lit.lower() if lit.lower() in {"pass", "fail", "blocked", "unresolved"} else lit
                    if lit_norm not in allowed_v and lit not in allowed_v:
                        findings.append(_emit_finding(
                            rule,
                            f"{os.path.relpath(agent_file, REPO_ROOT)}: emits verdict {lit!r} not in allowed_verdicts {sorted(allowed_v)}"
                        ))

        return findings


    def check_ledger_ownership(rule):
        """AOC v1 R2: gated_paths must be written only by allowed_writers.
        Scans template directories (.claude/agents, .claude/hooks,
        .claude/scripts, .claude/skills, .claude/patterns) for writes targeting
        gated_paths and reports any outside the allowed_writers list."""
        findings = []
        allowed = set(rule.get("allowed_writers", []))
        gated_paths = rule.get("gated_paths", [])
        # Build per-path escaped regex segments (literal paths).
        # Detect writes: patterns like "> .runs/fix-log.md", ">> .runs/fix-log.md",
        # "open('.runs/fix-log.md'", "open(\".runs/fix-log.md\"", and "with open('.runs/fix-log.md', 'a')".
        scan_roots = [
            ".claude/agents",
            ".claude/hooks",
            ".claude/scripts",
            ".claude/skills",
            ".claude/patterns",
        ]
        # Test directories contain fixture strings that intentionally reference
        # gated paths; do not scan them.
        SKIP_PREFIXES = (
            ".claude/scripts/tests/",
            ".claude/scripts/lib/tests/",
        )
        for gated in gated_paths:
            esc = re.escape(gated)
            write_patterns = [
                re.compile(r">{1,2}\s*" + esc),                             # shell redirect
                re.compile(r"open\(\s*['\"]" + esc + r"['\"]\s*,\s*['\"][wa]\+?b?['\"]"),  # open(path, 'w'/'a')
                re.compile(r"open\(\s*['\"]" + esc + r"['\"]\)[^)]*\.write\("),  # open(path).write( — rare
            ]
            for root in scan_roots:
                root_abs = os.path.join(REPO_ROOT, root)
                if not os.path.isdir(root_abs):
                    continue
                for dirpath, _dirs, files in os.walk(root_abs):
                    for fn in files:
                        if not (fn.endswith(".md") or fn.endswith(".sh")
                                or fn.endswith(".py") or fn.endswith(".json")):
                            continue
                        fpath = os.path.join(dirpath, fn)
                        relpath = os.path.relpath(fpath, REPO_ROOT)
                        # Skip the coherence rules file itself (declares paths as strings)
                        # and the contract docs.
                        if relpath == "/".join([".claude/patterns",
                                                "template-coherence-rules.json"]):
                            continue
                        if relpath == "/".join([".claude/patterns",
                                                "agent-output-contract.md"]):
                            continue
                        # Skip the linter itself: its regex patterns literally
                        # contain the gated paths for detection purposes.
                        if relpath == "/".join([".claude/scripts",
                                                "verify-linter.sh"]):
                            continue
                        # Skip the linter Python package — runner.py and its
                        # split-out modules contain the gated paths in detector
                        # regexes (this code itself is the detector).
                        if relpath.startswith(".claude/scripts/lib/linter/"):
                            continue
                        # Skip the runtime write guard: it contains the gated
                        # paths in its detection/deny regexes.
                        if relpath == "/".join([".claude/hooks",
                                                "fix-ledger-write-guard.sh"]):
                            continue
                        # Skip test fixtures.
                        if any(relpath.startswith(p) for p in SKIP_PREFIXES):
                            continue
                        if relpath in allowed:
                            continue  # Allowed writer; its writes are legitimate.
                        try:
                            content = open(fpath).read()
                        except OSError:
                            continue
                        for pat in write_patterns:
                            for m in pat.finditer(content):
                                # Skip when the mention is inside a code comment
                                # that references AOC v1 contract.
                                line_start = content.rfind("\n", 0, m.start()) + 1
                                line_end = content.find("\n", m.end())
                                if line_end == -1:
                                    line_end = len(content)
                                line = content[line_start:line_end]
                                low = line.lower()
                                if "aoc v1" in low or "# documented pattern" in low:
                                    continue
                                findings.append(_emit_finding(
                                    rule,
                                    f"{relpath}: writes to gated path {gated} outside allowed writers"
                                ))
                                break  # one finding per file+path
                            else:
                                continue
                            break
        return findings


    def check_gate_artifact_writer_enforcement(rule):
        """Issue #1299: writes to paths declared in
        gate-readable-artifacts-canonical.json must go through the canonical
        writer (.claude/scripts/lib/write-gate-artifact.sh) so {skill, run_id,
        written_at} stamping is automatic.

        Scans state files, agents, patterns, procedures, and helper scripts
        (.sh/.py) for write-syntax tokens targeting manifest paths. Read
        syntax (open(...,'r'), json.load, os.path.exists, [-f path], backtick
        prose) is allowlisted at line level (R2-C1) so the ~455 non-write
        mentions do not produce false-positive findings.

        Allowed writers: rule.allowed_writers + the canonical writer itself.
        Severity flips from warn to block in the chore/canonical-writer-
        migration-deny PR after the soak window confirms zero new-code-path
        friction entries.
        """
        findings = []
        allowed = set(rule.get("allowed_writers", []))
        # Always allow the canonical writer (it IS the canonical mechanism).
        allowed.add(".claude/scripts/lib/write-gate-artifact.sh")

        manifest_path = rule.get("manifest_path", "")
        manifest_abs = os.path.join(REPO_ROOT, manifest_path)
        if not os.path.isfile(manifest_abs):
            findings.append(_emit_finding(
                rule,
                f"manifest_path {manifest_path!r} does not exist",
            ))
            return findings
        try:
            manifest_data = json.load(open(manifest_abs))
        except (json.JSONDecodeError, OSError) as exc:
            findings.append(_emit_finding(
                rule,
                f"manifest_path {manifest_path!r} could not be parsed: {exc}",
            ))
            return findings
        gated = {a.get("path") for a in manifest_data.get("artifacts", [])}
        gated.discard(None)
        gated.discard("")
        if not gated:
            return findings  # Empty manifest = no enforcement.

        scan_corpus = rule.get("scan_corpus", [
            ".claude/skills",
            ".claude/agents",
            ".claude/patterns",
            ".claude/procedures",
            ".claude/scripts",
        ])
        # Test fixtures intentionally reference gated paths; skip them.
        SKIP_PREFIXES = (
            ".claude/scripts/tests/",
            ".claude/scripts/lib/tests/",
            ".claude/scripts/lib/linter/",  # the linter itself
        )
        # Specific files to skip (they ARE the canonical infrastructure).
        SKIP_FILES = {
            ".claude/scripts/lib/write-gate-artifact.sh",
            ".claude/scripts/append-hook-friction.py",
            ".claude/hooks/gate-artifact-write-gate.sh",
            ".claude/hooks/gate-artifact-bash-write-guard.sh",
            ".claude/patterns/gate-readable-artifacts-canonical.json",
            ".claude/patterns/template-coherence-rules.json",
            ".claude/patterns/agent-output-contract.md",
            ".claude/scripts/verify-linter.sh",
            ".claude/scripts/codemod-canonical-writer.py",
            ".claude/scripts/codemod-canonical-writer-audit.py",
        }

        # Read-syntax suppressors (R2-C1): if any matches on a line, do NOT
        # treat write-token matches on the same line as findings.
        READ_SUPPRESSORS = [
            re.compile(r"open\([^)]*,\s*['\"]r['\"]"),
            re.compile(r"\bjson\.load\b"),
            re.compile(r"\bos\.path\.exists\b"),
            re.compile(r"\[\s*-[fe]\s+"),
            re.compile(r"\bif\s+\[\s*!\s*-"),
        ]

        # Build a single regex alternation of all gated paths.
        gated_alt = "|".join(re.escape(p) for p in sorted(gated))
        # Write-syntax tokens (R2-C1): write-only.
        # PR-FIX-S2: replaced `json.dump([^()]*? open(...)` with a unified
        # `open(target, 'w'|'a')` matcher. The previous regex could not
        # span function calls in multi-line dict payloads (e.g.
        # datetime.now()), silently missing 9 sites. The unified pattern
        # uses a negative lookbehind to exclude the S1 form (`with open`).
        WRITE_PATTERNS = [
            # with open(target, 'w'|'a')
            re.compile(r"with\s+open\(\s*['\"](?P<path>" + gated_alt + r")['\"]\s*,\s*['\"][wa]"),
            # generic: any open(target, 'w'|'a') NOT preceded by `with ` —
            # covers json.dump(payload, open(target,'w')), payloads with
            # function calls, payloads spanning newlines, etc.
            re.compile(r"(?<!with\s)open\(\s*['\"](?P<path>" + gated_alt + r")['\"]\s*,\s*['\"][wa]"),
            # > target / >> target
            re.compile(r">{1,2}\s*(?P<path>" + gated_alt + r")\b"),
            # tee target
            re.compile(r"\btee\s+(?:-a\s+)?(?P<path>" + gated_alt + r")\b"),
            # cat > target <<EOF
            re.compile(r"cat\s+>\s*(?P<path>" + gated_alt + r")\s*<<"),
        ]

        for root in scan_corpus:
            root_abs = os.path.join(REPO_ROOT, root)
            if not os.path.isdir(root_abs):
                continue
            for dirpath, _dirs, files in os.walk(root_abs):
                for fn in files:
                    if not (fn.endswith(".md") or fn.endswith(".sh")
                            or fn.endswith(".py")):
                        continue
                    fpath = os.path.join(dirpath, fn)
                    relpath = os.path.relpath(fpath, REPO_ROOT)
                    if relpath in SKIP_FILES:
                        continue
                    if any(relpath.startswith(p) for p in SKIP_PREFIXES):
                        continue
                    if relpath in allowed:
                        continue
                    try:
                        content = open(fpath).read()
                    except OSError:
                        continue
                    seen_paths_in_file: set[str] = set()
                    for line_idx, line in enumerate(content.splitlines()):
                        if any(p.search(line) for p in READ_SUPPRESSORS):
                            continue
                        for pat in WRITE_PATTERNS:
                            m = pat.search(line)
                            if m is None:
                                continue
                            target = m.group("path")
                            if target not in gated:
                                continue
                            key = (relpath, target)
                            if key in seen_paths_in_file:
                                continue
                            seen_paths_in_file.add(key)
                            findings.append(_emit_finding(
                                rule,
                                f"{relpath}:{line_idx + 1}: direct write to "
                                f"gate-readable path {target} — "
                                f"use bash .claude/scripts/lib/write-gate-artifact.sh",
                            ))
                            break  # one finding per pattern per line
        return findings


    def check_consumer_coverage(rule):
        """AOC v1 R3: every consumer must reference canonical_source (path string)."""
        findings = []
        canonical = rule.get("canonical_source", "")
        consumers = rule.get("consumers", [])
        canonical_basename = os.path.basename(canonical)
        # The literal canonical path or its basename is sufficient evidence.
        needles = [canonical, canonical_basename]
        for consumer in consumers:
            fpath = os.path.join(REPO_ROOT, consumer)
            if not os.path.isfile(fpath):
                findings.append(_emit_finding(
                    rule,
                    f"{consumer}: consumer file missing"
                ))
                continue
            try:
                content = open(fpath).read()
            except OSError as e:
                findings.append(_emit_finding(
                    rule,
                    f"{consumer}: cannot read ({e})"
                ))
                continue
            if not any(n and n in content for n in needles):
                findings.append(_emit_finding(
                    rule,
                    f"{consumer}: does not reference canonical source {canonical}"
                ))
        return findings


    def check_audit_tag_claim_matches_ast(rule):
        """#1393 r3 Item 4 — for [audit:api-fetch=<path>] tags in experiment.yaml,
        assert generated page source actually contains a fetch('<path>') call
        (or compatible). Mirrors internal_href_validity rule's structural pattern."""
        findings = []
        registry_path = os.path.join(REPO_ROOT, rule.get("registry_path", ".claude/patterns/audit-verb-registry.json"))
        scaffold_glob = rule.get("scaffold_glob", "src/app/**/page.tsx")
        experiment_path = os.path.join(REPO_ROOT, rule.get("experiment_path", "experiment/experiment.yaml"))
        try:
            registry = json.load(open(registry_path))
        except (OSError, json.JSONDecodeError):
            return findings  # registry missing → handler skips (audit_tag_verb_recognized covers presence)
        ast_verbs = {
            v: m.get("value_type")
            for v, m in (registry.get("verbs") or {}).items()
            if m.get("consumer") == "ast-scanner"
        }
        if not ast_verbs:
            return findings
        if not os.path.isfile(experiment_path):
            return findings  # No experiment.yaml at scan time = nothing to check
        try:
            experiment_content = open(experiment_path).read()
        except OSError:
            return findings
        # Collect (verb, value) pairs from experiment.yaml
        tag_re = re.compile(r"\[audit:([a-zA-Z0-9_-]+)=([^\]]+)\]")
        claims = []
        for m in tag_re.finditer(experiment_content):
            verb, value = m.group(1), m.group(2).strip()
            if verb in ast_verbs:
                claims.append((verb, value))
        if not claims:
            return findings
        # Aggregate source from scaffolded pages
        source_blob = []
        for fp in glob.glob(os.path.join(REPO_ROOT, scaffold_glob), recursive=True):
            try:
                source_blob.append(open(fp).read())
            except OSError:
                pass
        combined = "\n".join(source_blob)
        for verb, value in claims:
            if verb == "api-fetch":
                # Require either fetch('<value>'), fetch("<value>"), or `<value>` in source
                needles = [f"fetch('{value}')", f'fetch("{value}")', f"fetch(`{value}`)"]
                if not any(n in combined for n in needles):
                    findings.append(_emit_finding(
                        rule,
                        f"experiment.yaml [audit:api-fetch={value}] but no matching fetch() call in {scaffold_glob}"
                    ))
            elif verb == "event":
                needles = [f"trackEvent('{value}'", f'trackEvent("{value}"', f"'{value}'", f'"{value}"']
                if not any(n in combined for n in needles):
                    findings.append(_emit_finding(
                        rule,
                        f"experiment.yaml [audit:event={value}] but no matching trackEvent() call in {scaffold_glob}"
                    ))
        return findings


    def check_cardinality_consistency_across_pipeline_steps(rule):
        """#1393 r3 Item 4 — for paired pipeline-step artifacts (prepass + merger
        per #1257 / PR #1357), assert partition.size and csi.length agree."""
        findings = []
        pairs = rule.get("pairs", [])
        for pair in pairs:
            a_path = os.path.join(REPO_ROOT, pair["a_path"])
            b_path = os.path.join(REPO_ROOT, pair["b_path"])
            a_field = pair["a_field"]  # e.g., "partition.size"
            b_field = pair["b_field"]  # e.g., "csi.length"
            if not (os.path.isfile(a_path) and os.path.isfile(b_path)):
                continue  # paired artifacts only exist after a run; skip pre-run
            try:
                a = json.load(open(a_path))
                b = json.load(open(b_path))
            except (OSError, json.JSONDecodeError):
                continue

            def _get(d, dotted):
                cur = d
                for k in dotted.split("."):
                    if isinstance(cur, dict):
                        cur = cur.get(k)
                    elif k == "length" and isinstance(cur, list):
                        cur = len(cur)
                    elif k == "size" and isinstance(cur, list):
                        cur = len(cur)
                    else:
                        return None
                return cur

            a_val = _get(a, a_field)
            b_val = _get(b, b_field)
            if a_val is None or b_val is None:
                continue
            if a_val != b_val:
                findings.append(_emit_finding(
                    rule,
                    f"cardinality drift: {pair['a_path']}.{a_field}={a_val} != {pair['b_path']}.{b_field}={b_val}"
                ))
        return findings


    def check_audit_tag_verb_recognized(rule):
        """#1393 r3 Item 3 — every `[audit:<verb>=<value>]` tag in experiment.yaml
        (or experiment-yaml.md docs) must use a verb declared in audit-verb-registry.json."""
        findings = []
        registry_path = os.path.join(REPO_ROOT, rule.get("registry_path", ".claude/patterns/audit-verb-registry.json"))
        scan_globs = rule.get("scan_globs", ["experiment/experiment.yaml", ".claude/templates/experiment-yaml.md"])
        if not os.path.isfile(registry_path):
            findings.append(_emit_finding(rule, f"registry missing: {registry_path}"))
            return findings
        try:
            registry = json.load(open(registry_path))
        except (OSError, json.JSONDecodeError) as e:
            findings.append(_emit_finding(rule, f"cannot parse registry: {e}"))
            return findings
        allowed = set((registry.get("verbs") or {}).keys())
        tag_re = re.compile(r"\[audit:([a-zA-Z0-9_-]+)=")
        for g in scan_globs:
            for fp in glob.glob(os.path.join(REPO_ROOT, g), recursive=True):
                try:
                    content = open(fp).read()
                except OSError:
                    continue
                for m in tag_re.finditer(content):
                    verb = m.group(1)
                    if verb not in allowed:
                        rel = os.path.relpath(fp, REPO_ROOT)
                        findings.append(_emit_finding(
                            rule,
                            f"{rel}: [audit:{verb}=...] uses unrecognized verb. "
                            f"Allowed verbs: {sorted(allowed)}. "
                            f"Add an entry to .claude/patterns/audit-verb-registry.json to extend."
                        ))
        return findings


    def check_derive_graim_manifest_carveout_pin(rule):
        """#1393 r3 Item 2 — pin the .jsonl carve-out. Assert (a) the docstring
        of derive-graim-manifest.py declares the carve-out, AND (b) the
        RE_RUNS_JSON regex still uses the negative lookahead that excludes .jsonl.
        Either change alone is a regression vector."""
        findings = []
        script_path = os.path.join(REPO_ROOT, ".claude/scripts/derive-graim-manifest.py")
        if not os.path.isfile(script_path):
            findings.append(_emit_finding(rule, f"missing: {script_path}"))
            return findings
        try:
            content = open(script_path).read()
        except OSError as e:
            findings.append(_emit_finding(rule, f"cannot read: {e}"))
            return findings
        if ".jsonl` telemetry is a known non-canonical class" not in content:
            findings.append(_emit_finding(
                rule,
                "derive-graim-manifest.py docstring missing the `.jsonl carve-out` declaration. "
                "DO NOT remove the docstring section without simultaneously updating the regex."
            ))
        if r"(?![a-zA-Z0-9])" not in content:
            findings.append(_emit_finding(
                rule,
                "derive-graim-manifest.py RE_RUNS_JSON missing the negative lookahead `(?![a-zA-Z0-9])` "
                "that excludes .jsonl. This is the single enforcement point — DO NOT remove without "
                "updating the docstring AND the gate-readable-artifacts-canonical.json header."
            ))
        return findings


    def check_hook_friction_action_type_classify(rule):
        """#1393 r3 Item 1 — scan procedure docs for sanctioned-manual-write
        markers (HTML-comment form: <!-- sanctioned-manual-write: <path> -->).
        Validates that every marker points to a path matching the canonical
        artifact pattern (.runs/*.json) AND that the host file actually
        contains lead-write instructions for that path (no stale markers).

        Output: enumerates the sanctioned-artifact set as a friction record
        if any host file declares a marker for a path it doesn't actually
        write. Future hooks/writers will consume this set to classify
        Write tool calls as manual-write-sanctioned vs manual-write-deviation."""
        findings = []
        scan_globs = rule.get("scan_globs", [".claude/patterns/*.md", ".claude/skills/**/state-*.md"])
        marker_re = re.compile(r"<!--\s*sanctioned-manual-write:\s*(.runs/[a-zA-Z0-9_./-]+\.json)\s*-->")
        for g in scan_globs:
            for fp in glob.glob(os.path.join(REPO_ROOT, g), recursive=True):
                try:
                    content = open(fp).read()
                except OSError:
                    continue
                for m in marker_re.finditer(content):
                    path = m.group(1)
                    # Stale-marker check: host file should reference the path
                    # as a write target somewhere (Write tool / write-gate-artifact.sh
                    # / direct mention in a write context).
                    if path not in content[m.end():] and path not in content[:m.start()]:
                        rel = os.path.relpath(fp, REPO_ROOT)
                        findings.append(_emit_finding(
                            rule,
                            f"{rel}: sanctioned-manual-write marker for {path} but file has no write reference (stale marker)"
                        ))
        return findings


    def check_verify_d_values_against_stamped_artifact(rule):
        """#1379 G1: state-registry.json VERIFY blocks must NOT iterate
        raw `d.values()` on a payload whose path is a gate-stamped artifact
        (registered in gate-readable-artifacts-canonical.json). The 3+
        stamped identity fields (skill, run_id, written_at, etc.) leak into
        the iteration and trip assertions like `all(v in (True, 'skipped'))`.

        Fix is to call `unstamped_values(d)` from .claude/scripts/lib/verify_helpers.py
        instead — see issue #1379 Gap 1."""
        findings = []
        registry_path = os.path.join(REPO_ROOT, rule.get("registry_path", ".claude/patterns/state-registry.json"))
        manifest_path = os.path.join(REPO_ROOT, rule.get("manifest_path", ".claude/patterns/gate-readable-artifacts-canonical.json"))
        if not os.path.isfile(registry_path):
            findings.append(_emit_finding(rule, f"registry missing: {registry_path}"))
            return findings
        if not os.path.isfile(manifest_path):
            findings.append(_emit_finding(rule, f"manifest missing: {manifest_path}"))
            return findings
        try:
            reg_text = open(registry_path).read()
            reg = json.loads(reg_text)
            manifest = json.load(open(manifest_path))
        except (OSError, json.JSONDecodeError) as e:
            findings.append(_emit_finding(rule, f"cannot parse: {e}"))
            return findings
        # Collect gate-stamped paths from manifest (anything that goes through
        # write-gate-artifact.sh per the GRAIM v2 canonical entries).
        stamped_paths = set()
        for entry in manifest.get("artifacts", []) or []:
            p = entry.get("path") or ""
            if p:
                stamped_paths.add(p)
        # Walk every VERIFY string in the registry. Match against `d.values()`
        # paired with a gate-stamped path. The state-registry uses single-string
        # VERIFY values (top-level) or dicts with a "verify" key (transient/cross-skill).
        states = reg.get("states", {}) if "states" in reg else reg
        # The registry schema mostly stores per-skill maps of state_id -> verify.
        # Walk all leaf strings that look like a python -c expression.
        def _walk(obj, path):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    _walk(v, path + [str(k)])
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    _walk(v, path + [str(i)])
            elif isinstance(obj, str):
                if "d.values()" not in obj:
                    return
                if "unstamped_values" in obj:
                    return  # already migrated
                # Identify which gate-stamped path this VERIFY references
                for sp in stamped_paths:
                    if sp in obj:
                        findings.append(_emit_finding(
                            rule,
                            f"state-registry path {'/'.join(path)}: VERIFY iterates raw d.values() against gate-stamped artifact {sp} — use unstamped_values(d) from .claude/scripts/lib/verify_helpers.py to skip {{skill, run_id, written_at, ...}} stamps"
                        ))
                        break
        _walk(reg, [])
        return findings


    def check_stage_0_detector_mode_aware(rule):
        """#1381 D3: every state file containing a "Stage 0" all-pages-fast-path
        detector MUST pair it with a bootstrap-verify mode skip (otherwise the
        detector fires inappropriately during bootstrap pre-commit). Semantic
        check, not heading-presence — must find both the Stage 0 trigger AND a
        skip predicate referencing verify-context.json.mode == "bootstrap-verify"
        within the same file."""
        findings = []
        scan_glob = rule.get("scan_glob", "")
        trigger_re = re.compile(rule.get("trigger_pattern", r"Stage 0"))
        mode_check_re = re.compile(rule.get("mode_check_pattern", r"bootstrap-verify"))
        for fp in glob.glob(os.path.join(REPO_ROOT, scan_glob), recursive=True):
            try:
                content = open(fp).read()
            except OSError:
                continue
            if not trigger_re.search(content):
                continue
            if not mode_check_re.search(content):
                rel = os.path.relpath(fp, REPO_ROOT)
                findings.append(_emit_finding(
                    rule,
                    f"{rel}: contains Stage 0 trigger but no bootstrap-verify mode skip predicate (#1381 D3 — detector fires inappropriately during bootstrap pre-commit because state-16 implementer commits create BOUNDARY_KIND=diff with PR_RELEVANT=0)"
                ))
        return findings


    def check_agent_registry_predicate_parity(rule):
        """#1381 D1: assert every agent in agent-registry.json hard_gates whose name
        starts with family_prefix has allow_predicates ⊇ baseline_agent's. Catches
        next sibling drift (e.g., adding design-quality-checker without parity)."""
        findings = []
        prefix = rule.get("family_prefix", "")
        baseline_name = rule.get("baseline_agent", "")
        reg_path = os.path.join(REPO_ROOT, ".claude/patterns/agent-registry.json")
        if not os.path.isfile(reg_path):
            findings.append(_emit_finding(rule, f"registry missing: {reg_path}"))
            return findings
        try:
            reg = json.load(open(reg_path))
        except (OSError, json.JSONDecodeError) as e:
            findings.append(_emit_finding(rule, f"cannot parse registry: {e}"))
            return findings
        hard_gates = reg.get("hard_gates", []) or []
        baseline_preds = None
        for entry in hard_gates:
            if entry.get("agent") == baseline_name:
                baseline_preds = set(entry.get("allow_predicates", []))
                break
        if baseline_preds is None:
            findings.append(_emit_finding(rule, f"baseline_agent {baseline_name!r} not found in hard_gates"))
            return findings
        for entry in hard_gates:
            name = entry.get("agent", "")
            if name == baseline_name or not name.startswith(prefix):
                continue
            preds = set(entry.get("allow_predicates", []))
            missing = baseline_preds - preds
            if missing:
                findings.append(_emit_finding(
                    rule,
                    f"{name}: allow_predicates missing {sorted(missing)} (parity with {baseline_name})"
                ))
        return findings


    def check_frontmatter_artifact_consistency(rule):
        """AOC v1.1 R4 (closes #1056): a verify-report.md frontmatter schema declares
        fields and consumers; the writer at schema_path.writer must emit every
        declared field, and every consumer must reference only declared field names
        (not stale or invented field names).

        Rule shape (template-coherence-rules.json):
          {
            "type": "frontmatter_artifact_consistency",
            "schema_path": ".claude/patterns/verify-report-frontmatter.json",
            "writer": ".claude/skills/verify/state-7a-write-report.md",
            "consumers": [...]
          }

        Findings emitted:
          - writer file does not contain a declared field
          - consumer references a field-like token that is NOT in the declared set
            (token = "<field>:" used as YAML/regex match; defends against stale
            names like build_attempt or fix_log_count drifting from canonical).
        """
        findings = []
        schema_path = rule.get("schema_path", "")
        writer_path = rule.get("writer", "")
        consumers = rule.get("consumers", [])

        if not schema_path or not writer_path:
            findings.append(_emit_finding(rule,
                "rule missing required schema_path or writer fields"))
            return findings

        schema_full = os.path.join(REPO_ROOT, schema_path)
        if not os.path.isfile(schema_full):
            findings.append(_emit_finding(rule,
                f"schema file not found: {schema_path}"))
            return findings
        try:
            schema = json.load(open(schema_full))
        except (OSError, json.JSONDecodeError) as e:
            findings.append(_emit_finding(rule,
                f"cannot parse schema {schema_path}: {e}"))
            return findings

        declared_fields = set(schema.get("fields", {}).keys())
        if not declared_fields:
            findings.append(_emit_finding(rule,
                f"schema {schema_path} declares no fields"))
            return findings

        # Resolve writer fields override from schema (the schema can name a writer
        # different from the rule, but if both are set they must agree).
        schema_writer = schema.get("writer", writer_path)
        if writer_path and schema_writer and writer_path != schema_writer:
            findings.append(_emit_finding(rule,
                f"writer mismatch: rule={writer_path!r} but schema={schema_writer!r}"))

        # Check writer emits every declared field
        writer_full = os.path.join(REPO_ROOT, writer_path)
        if not os.path.isfile(writer_full):
            findings.append(_emit_finding(rule,
                f"writer file not found: {writer_path}"))
        else:
            try:
                writer_content = open(writer_full).read()
            except OSError as e:
                findings.append(_emit_finding(rule,
                    f"cannot read writer {writer_path}: {e}"))
                writer_content = ""
            for field_name in sorted(declared_fields):
                # Match either YAML key form (`field_name:`) or quoted JSON key
                # form (`"field_name":`) — state-7a uses both.
                yaml_form = field_name + ":"
                if yaml_form not in writer_content:
                    findings.append(_emit_finding(rule,
                        f"writer {writer_path} does not emit declared field {field_name!r}"))

        # Check every consumer references ONLY declared fields. We look for any
        # token of the form `<word>:` that lives inside a context where the word
        # is plausibly a frontmatter field reference (preceded by `report.`,
        # `frontmatter.`, `verify-report`, or single-quoted as a key like
        # `'<word>'` near an open()-style read). Conservative: only flag tokens
        # that match \b(<words-with-frontmatter-shape>):\b and are referenced in
        # the consumer text.
        #
        # To avoid false positives from arbitrary `key: value` YAML in the
        # consumer's own files, we specifically look for the field names known to
        # appear in verify-report.md frontmatter (the declared set is finite and
        # small) and verify each consumer references at least one of them. If a
        # consumer uses a field-shaped name that resembles one of ours but is
        # NOT in the set, that's the stale-consumer signal we emit.
        declared_lc = {f.lower() for f in declared_fields}
        # Only multi-word snake_case names participate in stale-name detection.
        # This filters out single words like "score", "value", "type" that often
        # appear as YAML keys in unrelated content (e.g., q-score.md prose).
        # Multi-word frontmatter fields (build_attempts, hard_gate_failure, etc.)
        # are the primary drift surface — typos like build_attempt vs build_attempts
        # or fix_log_count vs fix_log_entries are exactly what this check catches.
        declared_multiword = {f.lower() for f in declared_fields if "_" in f}
        # Heuristic stale-name detection: scan for "<word_with_underscore>:" tokens
        # in consumer files that are similar to (Levenshtein <=2) but not equal to a
        # declared multi-word name. Single-word fields are checked only via the
        # writer-side "must emit declared field" check.
        import re as _re
        word_colon_re = _re.compile(r'\b([a-z][a-z0-9]*_[a-z0-9][a-z0-9_]*)\s*:')

        for consumer in consumers:
            cpath = os.path.join(REPO_ROOT, consumer)
            if not os.path.isfile(cpath):
                findings.append(_emit_finding(rule,
                    f"consumer file not found: {consumer}"))
                continue
            try:
                content = open(cpath).read()
            except OSError as e:
                findings.append(_emit_finding(rule,
                    f"cannot read consumer {consumer}: {e}"))
                continue
            # Confirm at least one declared field is referenced — otherwise the
            # consumer isn't really consuming this frontmatter (perhaps a stale
            # entry in the rule's consumers list).
            any_declared = any(f in content for f in declared_fields)
            if not any_declared:
                findings.append(_emit_finding(rule,
                    f"consumer {consumer} does not reference any declared frontmatter field "
                    f"(check the consumers list for staleness)"))
                continue
            # Stale-name detection: find multi-word snake_case tokens in consumer
            # files that aren't declared but resemble a declared multi-word field.
            # Compare by edit distance — anything 1-2 edits away from a multi-word
            # declared name is suspicious (likely typo or stale rename).
            seen_unknown = set()
            for m in word_colon_re.finditer(content):
                token = m.group(1).lower()
                if token in declared_lc:
                    continue
                # Only compare against multi-word declared fields (single-word
                # comparisons produce too many false positives for prose content).
                for declared in declared_multiword:
                    if abs(len(token) - len(declared)) > 2:
                        continue
                    if token[:3] == declared[:3] and (
                        _edit_distance_le(token, declared, 2)
                    ):
                        if token in seen_unknown:
                            break
                        seen_unknown.add(token)
                        findings.append(_emit_finding(rule,
                            f"consumer {consumer} references {token!r} which is not in "
                            f"declared frontmatter fields (closest: {declared!r}; check for "
                            "typos / stale field names)"))
                        break

        return findings


    def _edit_distance_le(a, b, max_dist):
        """Return True if Levenshtein(a, b) <= max_dist. Cheap iterative DP."""
        if abs(len(a) - len(b)) > max_dist:
            return False
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            curr = [i] + [0] * len(b)
            for j, cb in enumerate(b, 1):
                cost = 0 if ca == cb else 1
                curr[j] = min(curr[j-1] + 1, prev[j] + 1, prev[j-1] + cost)
            prev = curr
            if min(prev) > max_dist:
                return False
        return prev[-1] <= max_dist


    def check_internal_href_validity(rule):
        """#1069 cross-agent fixture contract: walk scaffold-emitted files for
        href="/<route>/<slug-or-id>" patterns; for each route matching a configured
        prefix, parse the canonical fixture file (if it exists) and verify every
        referenced identifier appears as a literal string. Fabricated IDs emit a
        cross_file_contradiction finding at WARN severity."""
        findings = []
        scaffold_glob = rule.get("scaffold_glob", "")
        hints = rule.get("route_owner_hints", [])
        if not scaffold_glob or not hints:
            return findings

        import glob as _glob
        import re as _re
        scaffold_files = []
        for pattern in scaffold_glob.split(","):
            pattern = pattern.strip()
            if pattern:
                scaffold_files.extend(_glob.glob(pattern, recursive=True))
        if not scaffold_files:
            return findings

        # Pre-load canonical fixture contents (first matching candidate wins).
        route_to_fixture = {}
        for hint in hints:
            prefix = hint.get("route_prefix", "")
            if not prefix:
                continue
            for candidate in hint.get("fixture_candidates", []):
                if os.path.isfile(candidate):
                    try:
                        with open(candidate) as f:
                            route_to_fixture[prefix] = (candidate, f.read())
                        break
                    except OSError:
                        continue

        # Walk scaffold files for href patterns per configured prefix.
        href_re = _re.compile(r'href\s*=\s*[{"`]\s*[`"]?(/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)[`"]?')
        template_re = _re.compile(r'href\s*=\s*\{\s*`(/[a-zA-Z0-9_-]+/)\$\{([^}]+)\}`\s*\}')
        for sf in scaffold_files:
            try:
                with open(sf) as f:
                    content = f.read()
            except OSError:
                continue
            for m in href_re.finditer(content):
                route = m.group(1)
                for prefix, (fixture_path, fixture_content) in route_to_fixture.items():
                    if not route.startswith(prefix):
                        continue
                    slug = route[len(prefix):]
                    # Skip template-literal-looking values ($, {, }).
                    if any(ch in slug for ch in "${}`"):
                        continue
                    if slug and slug not in fixture_content:
                        findings.append(_emit_finding(
                            rule,
                            f"{sf}: href {route!r} references {slug!r} which does not appear in canonical fixture {fixture_path}"
                        ))
                    break
        return findings


    def check_pages_no_payload_type_exports(rule):
        """#1161 (b): block payload-shape type declarations in page files.

        Pattern A (suffix): `(export )?(type|interface) X<suffix>` where suffix
        is in {Payload, Response, Request, Schema}. Catches both exported and
        local declarations (round-2 Concern 3 fix).

        Pattern B (collision): name matches an exported type from
        types_source_path (default src/lib/types.ts).

        Both patterns scope to scope_glob minus path_excludes (fnmatch on full
        path) and filename_excludes (fnmatch on basename).
        """
        import fnmatch as _fnmatch
        import glob as _glob
        import re as _re

        findings = []
        scope_glob = rule.get("scope_glob", "")
        path_excludes = rule.get("path_excludes", [])
        filename_excludes = rule.get("filename_excludes", [])
        suffix_pat = rule.get(
            "suffix_pattern",
            r"^(export\s+)?(type|interface)\s+[A-Z][a-zA-Z0-9]*(Payload|Response|Request|Schema)\s*[<{=]",
        )
        types_source = rule.get("types_source_path", "src/lib/types.ts")

        if not scope_glob:
            return findings

        candidate_files = []
        for pat in scope_glob.split(","):
            pat = pat.strip()
            if pat:
                candidate_files.extend(_glob.glob(pat, recursive=True))

        def is_excluded(path):
            for ex in path_excludes:
                if _fnmatch.fnmatch(path, ex):
                    return True
            base = os.path.basename(path)
            for fx in filename_excludes:
                if _fnmatch.fnmatch(base, fx):
                    return True
            return False

        scope_files = sorted(set(f for f in candidate_files if not is_excluded(f)))

        suffix_re = _re.compile(suffix_pat, _re.MULTILINE)

        types_names = set()
        if os.path.isfile(types_source):
            try:
                with open(types_source) as f:
                    content = f.read()
                for m in _re.finditer(
                    r"^export\s+(type|interface)\s+([A-Z][a-zA-Z0-9]*)",
                    content,
                    _re.MULTILINE,
                ):
                    types_names.add(m.group(2))
                for m in _re.finditer(
                    r"^export\s+(type|interface)?\s*\{\s*([^}]+)\s*\}",
                    content,
                    _re.MULTILINE,
                ):
                    for raw in m.group(2).split(","):
                        n = raw.strip().split(" as ")[0].strip()
                        if _re.match(r"^[A-Z][a-zA-Z0-9]*$", n):
                            types_names.add(n)
            except OSError:
                pass

        collision_res = {
            name: _re.compile(
                rf"^(export\s+)?(type|interface)\s+{_re.escape(name)}\s*[<{{=]",
                _re.MULTILINE,
            )
            for name in types_names
        }

        for sf in scope_files:
            try:
                with open(sf) as f:
                    content = f.read()
            except OSError:
                continue

            for m in suffix_re.finditer(content):
                line_no = content[: m.start()].count("\n") + 1
                snippet = m.group(0).strip()
                findings.append(
                    _emit_finding(
                        rule,
                        f"{sf}:{line_no}: payload-shape type declaration `{snippet}` — "
                        f"move to {types_source} (owned by scaffold-wire) or use TypeScript inference",
                    )
                )

            for name, collision_re in collision_res.items():
                for m in collision_re.finditer(content):
                    line_no = content[: m.start()].count("\n") + 1
                    findings.append(
                        _emit_finding(
                            rule,
                            f"{sf}:{line_no}: type name `{name}` collides with {types_source} export — "
                            f"import from @/lib/types instead of redefining",
                        )
                    )

        return findings


    def check_must_contain_section(rule):
        """Verify files matching `applies_to_glob` contain a `required_section`
        heading whenever any of `trigger_pattern_any` regex matches their content.

        Rule shape:
          {
            "id": "<rule_id>",
            "type": "must_contain_section",
            "severity": "block" | "warn",
            "applies_to_glob": "<glob path>",                  # e.g. ".claude/stacks/**/*.md"
            "required_section": "## Section Heading",          # literal match required
            "trigger_pattern_any": ["regex1", "regex2", ...],  # if ANY regex matches → required_section MUST be present
            "exclude_glob": ["path1", "path2", ...]            # optional: skip these paths/globs
          }

        Rationale: stack files prescribing env-gated source code (e.g.,
        `?? "phc_TEAM_KEY"`, `|| "placeholder-stripe-publishable"`) must
        include a documented `## Production Observability` story so future
        downstream consumers understand the fail-loud contract. Otherwise
        the silent-fallback antipattern recurs (issue #1170 lineage).

        Conservative semantics:
          - Trigger patterns are evaluated against full file contents (no
            heading-aware exclusion). False positives are filtered by
            `exclude_glob` if needed.
          - `required_section` is matched as a literal substring; the rule
            does not parse markdown structure. This intentionally allows
            the heading to appear in any section depth (## or ###).
          - Failure mode: the file matched a trigger pattern but does NOT
            contain the required heading anywhere → emit one finding per
            (file, trigger pattern) pair so the author sees which trigger
            fired.
        """
        out = []
        rid = rule.get("id", "<unknown>")
        applies_glob = rule.get("applies_to_glob", "")
        required_section = rule.get("required_section", "")
        trigger_patterns = rule.get("trigger_pattern_any", [])
        exclude_globs = rule.get("exclude_glob", []) or []

        if not applies_glob or not required_section or not trigger_patterns:
            return out  # under-specified rule — surfaced by schema validation

        try:
            compiled = [re.compile(p) for p in trigger_patterns]
        except re.error as e:
            out.append(f"  [{rid}] invalid regex in trigger_pattern_any: {e}")
            return out

        # fnmatch-style exclusion via glob.fnmatch.translate
        import fnmatch
        def _excluded(path):
            for g in exclude_globs:
                if fnmatch.fnmatch(path, g):
                    return True
            return False

        files = sorted(glob.glob(os.path.join(REPO_ROOT, applies_glob), recursive=True))
        for fpath in files:
            rel = os.path.relpath(fpath, REPO_ROOT)
            if _excluded(rel):
                continue
            try:
                content = open(fpath, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue

            if required_section in content:
                continue  # heading present — no-op even if triggers match

            for i, cre in enumerate(compiled):
                m = cre.search(content)
                if not m:
                    continue
                trig_repr = trigger_patterns[i]
                line_no = content[: m.start()].count("\n") + 1
                out.append(
                    f"  [{rid}] {rel}:{line_no} matches trigger /{trig_repr}/ "
                    f"but is missing required section '{required_section}'"
                )

        return out


    def check_events_yaml_seeded_from_stack_emits_events(rule):
        """Issue #1447 Rule D — every event listed in ACTIVE stack files'
        frontmatter `emits_events:` list MUST appear as a top-level key under
        `events:` in experiment/EVENTS.yaml. Cross-file enum-membership audit.

        ACTIVE stacks are derived from `experiment/experiment.yaml`'s `stack:`
        section, using the CLAUDE.md Rule 3 category mapping:
          - Shared: stack.{database,auth,analytics,payment,email,ai,...}
                    → .claude/stacks/<category>/<value>.md
          - Per-service: stack.services[].{runtime,hosting,ui,testing}
                    → .claude/stacks/{framework,hosting,ui,testing}/<value>.md

        Primary enforcement is /spec state-6 step 9 which seeds these events
        during EVENTS.yaml assembly. This rule catches drift.

        Rule shape:
          {
            "id": "<rule_id>",
            "type": "events_yaml_seeded_from_stack_emits_events",
            "severity": "block" | "warn",
            "stack_glob": ".claude/stacks/**/*.md",      # optional, default shown
            "events_yaml_path": "experiment/EVENTS.yaml", # optional, default shown
            "exclude_stack_glob": ["path1", "path2"]      # optional, fnmatch patterns
          }

        No-op when:
          - events_yaml_path does not exist
          - experiment.yaml does not exist
          - experiment.yaml has no `stack:` section
        These conditions identify the template repo / non-bootstrapped projects.
        """
        import fnmatch
        out = []
        rid = rule.get("id", "<unknown>")
        stack_glob = rule.get("stack_glob", ".claude/stacks/**/*.md")
        events_yaml_path = rule.get("events_yaml_path", "experiment/EVENTS.yaml")
        exclude_globs = rule.get("exclude_stack_glob", []) or []

        events_yaml_full = os.path.join(REPO_ROOT, events_yaml_path)
        experiment_yaml_full = os.path.join(REPO_ROOT, "experiment/experiment.yaml")
        if not os.path.isfile(events_yaml_full) or not os.path.isfile(experiment_yaml_full):
            return out

        try:
            import yaml as _yaml
            events_data = _yaml.safe_load(open(events_yaml_full, encoding="utf-8")) or {}
            events_declared = set((events_data.get("events") or {}).keys())
            exp_data = _yaml.safe_load(open(experiment_yaml_full, encoding="utf-8")) or {}
        except Exception as e:
            out.append(f"  [{rid}] failed to parse experiment/EVENTS.yaml or experiment.yaml: {e}")
            return out

        stack_section = exp_data.get("stack") or {}
        if not isinstance(stack_section, dict) or not stack_section:
            return out  # template / unconfigured experiment

        # Skip when EVENTS.yaml is in its placeholder state (empty events map).
        # This means /spec has not yet run for this project — drift cannot
        # exist before the seeding step has executed. After /spec runs, events
        # is non-empty and Rule D activates for real bootstrapped projects.
        if not events_declared:
            return out

        # Derive active stack file paths from experiment.yaml.
        # Per-service category mapping per CLAUDE.md Rule 3.
        SERVICE_KEY_TO_CATEGORY = {
            "runtime": "framework",
            "hosting": "hosting",
            "ui": "ui",
            "testing": "testing",
        }
        active_stacks = set()
        for key, value in stack_section.items():
            if key == "services":
                services = value or []
                if not isinstance(services, list):
                    continue
                for svc in services:
                    if not isinstance(svc, dict):
                        continue
                    for svc_key, svc_val in svc.items():
                        if svc_key in SERVICE_KEY_TO_CATEGORY and isinstance(svc_val, str):
                            category = SERVICE_KEY_TO_CATEGORY[svc_key]
                            active_stacks.add(f".claude/stacks/{category}/{svc_val}.md")
            elif isinstance(value, str):
                # Shared category: stack.<key>: <value>
                active_stacks.add(f".claude/stacks/{key}/{value}.md")

        def _excluded(rel_path):
            for g in exclude_globs:
                if fnmatch.fnmatch(rel_path, g):
                    return True
            return False

        for sf in sorted(glob.glob(os.path.join(REPO_ROOT, stack_glob), recursive=True)):
            rel = os.path.relpath(sf, REPO_ROOT)
            if _excluded(rel):
                continue
            if rel not in active_stacks:
                continue  # stack file exists but is not in this experiment's stack section
            try:
                content = open(sf, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            m = re.match(r"^---\n(.*?\n)---", content, re.DOTALL)
            if not m:
                continue
            try:
                import yaml as _yaml
                fm = _yaml.safe_load(m.group(1)) or {}
            except Exception:
                continue
            emits = fm.get("emits_events")
            if not isinstance(emits, list):
                continue
            for ev in emits:
                if not isinstance(ev, str):
                    continue
                if ev not in events_declared:
                    out.append(
                        f"  [{rid}] {events_yaml_path}: active stack {rel} declares emits_events: [{ev}] "
                        f"but '{ev}' is missing from events: map. Run /spec state-6 step 9 to seed "
                        f"framework-emitted events, or add the event manually."
                    )
        return out


    def check_bash_hook_write_operator_binding(rule):
        """Issue #1236 — class-level prevention for the unbound-co-occurrence
        regex anti-pattern in Bash-matcher write-guard hooks.

        Phase 1: every entry in manifest_path must (a) point at an existing hook,
        (b) have its protected_path_regex literal appear in the hook source
        (proving it is referenced inside a bound-target match()), and (c) have
        every declared write_operator referenced in the hook source.

        Phase 2: scan_glob (CSV of globs) is searched for two historical
        anti-pattern shapes — `grep -qE '<write-op>.*<path>'` (the #1230 / pre-
        #1185 shape) and `awk '/<path>/ && /(<write-op>)/'` (original co-
        occurrence). Any match in an unregistered hook fires a 'must register'
        finding. Pragma `# coherence-allow: unbound-fastpath` within ±5 lines
        suppresses.

        Phase 3 (#1298): every registered hook MUST canonicalize $COMMAND via
        canonicalize_bash_command.py before running shell-redirect or allow-list
        regex matches on it. Heredoc-body data text in raw $COMMAND otherwise
        produces false positives. Each registered hook source must contain a
        canonicalize_bash_command.py invocation; any raw "$COMMAND" reference
        AFTER that line requires pragma `# coherence-allow: raw-command` within
        ±5 lines (escape hatch for python-source / variable-indirection
        regexes that intentionally consume RAW to catch heredoc-fed attacks
        like `python3 <<PY ... open('<protected>','w') ... PY`).
        """
        out = []
        rid = rule.get("id", "<unknown>")
        manifest_path = rule.get("manifest_path", "")
        scan_glob_csv = rule.get("scan_glob", "")
        pragma = rule.get("pragma", "# coherence-allow: unbound-fastpath")
        pragma_phase3 = rule.get("pragma_phase3", "# coherence-allow: raw-command")

        manifest_full = os.path.join(REPO_ROOT, manifest_path)
        if not os.path.isfile(manifest_full):
            out.append(_emit_finding(rule, f"manifest missing: {manifest_path}"))
            return out
        try:
            manifest = json.load(open(manifest_full))
        except (OSError, json.JSONDecodeError) as e:
            out.append(_emit_finding(rule, f"manifest parse error: {e}"))
            return out

        write_guards = manifest.get("write_guards", [])
        registered_hooks = {entry["hook"] for entry in write_guards if "hook" in entry}

        # Phase 1 — Manifest verification
        for entry in write_guards:
            hook = entry.get("hook")
            ppr = entry.get("protected_path_regex")
            ops = entry.get("write_operators", [])
            if not hook or not ppr or not ops:
                out.append(_emit_finding(
                    rule, f"manifest entry incomplete (need hook+protected_path_regex+write_operators): {entry}"
                ))
                continue
            hook_full = os.path.join(REPO_ROOT, hook)
            if not os.path.isfile(hook_full):
                out.append(_emit_finding(rule, f"{hook}: manifest entry points at nonexistent file"))
                continue
            try:
                content = open(hook_full).read()
            except OSError:
                continue
            if ppr not in content:
                out.append(_emit_finding(
                    rule, f"{hook}: protected_path_regex literal '{ppr}' not found in source — bound-target match() missing"
                ))
                continue
            for op in ops:
                # Word-like operators (alphanumeric) need word-boundary checks so
                # 'dd' doesn't false-pass on 'embedded' / '.add', etc. Symbol
                # operators ('>', '>>', '&?>') are checked via plain substring.
                if op.replace("?", "").isalnum():
                    pat = re.compile(r"\b" + re.escape(op) + r"\b")
                    if not pat.search(content):
                        out.append(_emit_finding(
                            rule, f"{hook}: declared write_operator '{op}' missing from bound-target detection"
                        ))
                else:
                    if op not in content:
                        out.append(_emit_finding(
                            rule, f"{hook}: declared write_operator '{op}' missing from bound-target detection"
                        ))

        # Phase 2 — Anti-pattern scan across scan_glob
        # Shape A: `grep -qE '<write-op>.*<path>'` or `grep -qE '<path>.*<write-op>'`
        # The presence of `.*` between a write-op token and a path-like literal
        # in a single grep regex is the historical bug shape (no positional
        # binding). Detection: a grep -qE / -E quoted body that contains BOTH
        # a write-op token AND `.*`.
        grep_body_re = re.compile(
            r"grep\s+-(?:q[a-zA-Z]*E|E[a-zA-Z]*q?|qE|Eq)\s+(['\"])([^'\"]+)\1",
            re.MULTILINE,
        )
        # Shape B: `awk '/<path>/ && /(<op>)/'` — co-occurrence joined by &&
        # without positional binding. Detection: an awk single-quoted body
        # that contains BOTH `&&` joining two regex literals AND a write-op
        # token. We use a coarse two-step check (find awk body, then inspect)
        # so we don't have to enumerate every awk regex shape.
        awk_body_re = re.compile(r"awk\b[^|;\n]*?'([^']*?&&[^']*)'", re.MULTILINE)

        # Word-boundary-aware write-op detector for body inspection. Matches
        # both symbol ops (>, >>, &>) and word ops (tee, cp, mv, dd) — but
        # word ops must have non-alphanumeric (or quote/space) boundary.
        body_write_op_re = re.compile(
            r"&?>>?|"
            r"(?:^|[\s/(|])(?:tee|cp|mv|dd)(?=[\s/)$|*]|$)"
        )
        # Path-like literal heuristic: a /something/ regex with at least 4
        # non-slash chars between slashes. Distinguishes `/agent-traces/`
        # from `/(>|>>)/` (which has no inner content).
        path_literal_re = re.compile(r"/[^/\s]{4,}/")

        # Pragma open-marker derivation. Accepts both the bare form and a
        # reason-suffixed variant (e.g., `# coherence-allow: unbound-fastpath: <why>`)
        # by matching only the prefix before the closing comment marker. Uses
        # `split(" -->", 1)[0]` rather than rstrip(" -->") which is a char-
        # class strip, not a substring strip — fragile if pragma name ended
        # with `-` or `>`.
        if pragma.endswith(" -->"):
            pragma_prefix = pragma[:-len(" -->")]
        else:
            pragma_prefix = pragma

        for sg in [g.strip() for g in scan_glob_csv.split(",") if g.strip()]:
            for fpath in sorted(glob.glob(os.path.join(REPO_ROOT, sg), recursive=True)):
                rel = os.path.relpath(fpath, REPO_ROOT)
                # Registered hooks are manifest-verified above; skip the
                # anti-pattern scan to avoid duplicate findings on legitimate
                # post-fix bound shapes.
                if rel in registered_hooks:
                    continue
                try:
                    content = open(fpath).read()
                except OSError:
                    continue
                file_lines = content.split("\n")

                def _pragma_in_window(match_start):
                    """±5-line window matches the markdown rule for consistency."""
                    line_idx = content[:match_start].count("\n")
                    win = "\n".join(file_lines[
                        max(0, line_idx - 5):
                        min(len(file_lines), line_idx + 6)
                    ])
                    return pragma_prefix in win

                # Shape A: grep -qE body containing both a write-op token and `.*`
                for m in grep_body_re.finditer(content):
                    body = m.group(2)
                    if ".*" not in body:
                        continue
                    if not body_write_op_re.search(body):
                        continue
                    if _pragma_in_window(m.start()):
                        continue
                    line_no = content[: m.start()].count("\n") + 1
                    out.append(_emit_finding(
                        rule,
                        f"{rel}:{line_no} matches anti-pattern 'grep-with-.*' but hook is "
                        f"not registered in {manifest_path}"
                    ))

                # Shape B: awk single-quoted body containing && and a write-op
                # and at least one path-like regex literal.
                for m in awk_body_re.finditer(content):
                    body = m.group(1)
                    if not body_write_op_re.search(body):
                        continue
                    if not path_literal_re.search(body):
                        continue
                    if _pragma_in_window(m.start()):
                        continue
                    line_no = content[: m.start()].count("\n") + 1
                    out.append(_emit_finding(
                        rule,
                        f"{rel}:{line_no} matches anti-pattern 'awk-co-occurrence' but hook is "
                        f"not registered in {manifest_path}"
                    ))

        # Phase 3 — Canonicalization enforcement (#1298)
        #
        # Each registered hook must canonicalize $COMMAND via
        # canonicalize_bash_command.py before running shell-redirect / allow-list
        # regex matches. Any raw "$COMMAND" reference AFTER the canonicalize
        # line requires pragma `# coherence-allow: raw-command` within ±5 lines.
        canonicalize_marker = "canonicalize_bash_command.py"
        # Match a literal `"$COMMAND"` reference (the dollar-sign-quoted form
        # used in `echo "$COMMAND"` / `printf '%s' "$COMMAND"` / `case "$COMMAND" in`).
        # Excludes `"$COMMAND_CANONICAL"` and the assignment line `COMMAND=...`.
        raw_command_re = re.compile(r'"\$COMMAND"')

        # Pragma matcher reuses the open-marker derivation from Phase 2.
        if pragma_phase3.endswith(" -->"):
            phase3_prefix = pragma_phase3[:-len(" -->")]
        else:
            phase3_prefix = pragma_phase3

        for entry in write_guards:
            hook = entry.get("hook")
            if not hook:
                continue
            hook_full = os.path.join(REPO_ROOT, hook)
            if not os.path.isfile(hook_full):
                continue  # Phase 1 already flagged
            try:
                content = open(hook_full).read()
            except OSError:
                continue

            # Find the canonicalize invocation line (first occurrence).
            canon_pos = content.find(canonicalize_marker)
            if canon_pos == -1:
                out.append(_emit_finding(
                    rule,
                    f"{hook}: missing {canonicalize_marker} invocation — "
                    f"registered hook must canonicalize $COMMAND before regex matching (#1298)"
                ))
                continue

            file_lines = content.split("\n")

            def _phase3_pragma_in_window(match_start, _content=content, _lines=file_lines):
                line_idx = _content[:match_start].count("\n")
                win = "\n".join(_lines[
                    max(0, line_idx - 5):
                    min(len(_lines), line_idx + 6)
                ])
                return phase3_prefix in win

            # Find every raw "$COMMAND" reference after the canonicalize line.
            for m in raw_command_re.finditer(content, canon_pos + len(canonicalize_marker)):
                if _phase3_pragma_in_window(m.start()):
                    continue
                line_no = content[: m.start()].count("\n") + 1
                out.append(_emit_finding(
                    rule,
                    f"{hook}:{line_no} raw \"$COMMAND\" reference after canonicalize line "
                    f"requires pragma '{phase3_prefix}' within ±5 lines (#1298)"
                ))
        return out


    def check_markdown_cross_file_line_reference(rule):
        """Issue #1238 — flags stale line-number cross-references in template
        markdown.

        Branch 1 (cross-file): emits when a line-number qualifier (`(line N)`,
        `lines N-M`, `L\\d+-\\d+`, `on line N`) co-occurs within a 3-line window
        with a path-mention to a template-eligible file (extensions: md, yaml,
        yml, json, py, sh; src/-prefixed paths excluded — src/ is scaffold-
        emitted code that the rule deliberately ignores).

        Branch 2 (same-file): emits when the qualifier appears with NO
        path-mention in the 3-line window. Covers self-references that rot when
        the same file is edited.

        Pragma <!-- coherence-allow: line-number-cross-reference --> on the same
        line or within ±1 line suppresses both branches.
        """
        out = []
        rid = rule.get("id", "<unknown>")
        target_glob = rule.get("target_glob", "")
        pragma = rule.get("pragma", "<!-- coherence-allow: line-number-cross-reference -->")

        # Path-mention: file with template-eligible extension; src/ prefix excluded
        # for Branch 1 attribution (src/ is scaffold-emitted code, not template-rot).
        path_mention_re = re.compile(
            r"(?:^|[^a-zA-Z0-9./_-])"
            r"(?!src/)"
            r"((?!.*/src/)[a-zA-Z][\w.-]*(?:/[\w.-]+)*\.(?:md|yaml|yml|json|py|sh))"
        )
        # Any-path mention (INCLUDING src/) — used to suppress Branch 2 when a
        # src/ path is the implicit subject of the line-number reference (e.g.,
        # "src/lib/stripe.ts already throws when KEY is missing (line 60-62)").
        any_path_mention_re = re.compile(
            r"[a-zA-Z][\w./-]*\.(?:md|yaml|yml|json|py|sh|tsx?|jsx?|css|sql)"
        )
        # Line-number qualifier — requires a strong citation signal to avoid
        # false-positives on prose phrases like "Description line 1" (Google
        # Ads label) or "line 14" used as content rather than a reference.
        # Accepted forms:
        #   - `(line N)` or `(line N-M)` — parenthesized citation
        #   - `(lines N-M)` — parenthesized range
        #   - `L\d+-\d+` — L-prefix with range
        #   - `on line N` / `on lines N-M` — explicit citation
        #   - `lines N-M` / `lines N to M` — explicit range
        # Standalone "line N" (no parens, no range, no "on") is intentionally
        # not matched — too ambiguous with content prose.
        line_num_re = re.compile(
            r"\(\s*line\s+\d+(?:\s*[-–]\s*\d+)?\s*\)"
            r"|\(\s*lines\s+\d+\s*[-–]\s*\d+\s*\)"
            r"|\bL\d+\s*[-–]\s*\d+\b"
            r"|\bon\s+lines?\s+\d+(?:\s*[-–]\s*\d+|\s+to\s+\d+)?\b"
            r"|\blines\s+\d+\s*[-–]\s*\d+\b"
            r"|\blines\s+\d+\s+to\s+\d+\b",
            re.IGNORECASE,
        )

        def _expand_braces(glob_pat):
            m = re.search(r"\{([^{}]+)\}", glob_pat)
            if not m:
                return [glob_pat]
            results = []
            for choice in m.group(1).split(","):
                results.extend(_expand_braces(
                    glob_pat[: m.start()] + choice + glob_pat[m.end():]
                ))
            return results

        seen = set()
        for expanded in _expand_braces(target_glob):
            for fpath in sorted(glob.glob(os.path.join(REPO_ROOT, expanded), recursive=True)):
                if fpath in seen:
                    continue
                seen.add(fpath)
                rel = os.path.relpath(fpath, REPO_ROOT)
                try:
                    lines = open(fpath, encoding="utf-8").read().split("\n")
                except (OSError, UnicodeDecodeError):
                    continue
                # Treat pragma as a prefix: the rule accepts both the bare
                # form `<!-- coherence-allow: line-number-cross-reference -->`
                # and reason-suffixed forms like `... -reference: <why> -->`.
                # Strip the trailing ` -->` substring (NOT character-class
                # strip — rstrip(" -->") is by char set {' ', '-', '>'} and
                # would corrupt prefixes ending in `-` or `>`).
                if pragma.endswith(" -->"):
                    pragma_prefix = pragma[:-len(" -->")]
                else:
                    pragma_prefix = pragma
                # Pragma window is ±5 lines. Wider than ±1 to cover fenced code
                # blocks and tables where multiple consecutive references share
                # one bracketing pragma. Narrow enough that a stray pragma far
                # from the reference doesn't accidentally suppress new rot.
                for i, line in enumerate(lines):
                    qm = line_num_re.search(line)
                    if not qm:
                        continue
                    pragma_window = "\n".join(lines[max(0, i - 5): min(len(lines), i + 6)])
                    if pragma_prefix in pragma_window:
                        continue
                    window = "\n".join(lines[max(0, i - 1): min(len(lines), i + 2)])
                    pm = path_mention_re.search(window)
                    snippet = line.strip()
                    if len(snippet) > 100:
                        snippet = snippet[:100] + "..."
                    if pm:
                        out.append(_emit_finding(
                            rule,
                            f"{rel}:{i + 1} cross-file line-number reference to '{pm.group(1)}': '{snippet}'"
                        ))
                    else:
                        # Branch 2 suppression: if a src/ path or other path-like
                        # token appears in the window, the line-number is the
                        # implicit subject of that path — not a same-file rot
                        # reference. Avoids false-positives on prose like
                        # "src/lib/stripe.ts already throws (line 60-62)".
                        if any_path_mention_re.search(window):
                            continue
                        out.append(_emit_finding(
                            rule,
                            f"{rel}:{i + 1} same-file line-number reference (no path mention): '{snippet}'"
                        ))
        return out


    def check_lead_orchestrated_eligibility_complete(rule):
        """AOC v1.2 F7 — assert that every agent in
        (verdict_agents - recovery_forbidden - lead_orchestrated_forbidden)
        with a hard_gates entry includes pass_lead_orchestrated in
        allow_predicates, AND no agent in lead_orchestrated_forbidden has
        it whitelisted (drift in either direction).

        Closes design caveat C5: per-agent eligibility derives mechanically
        from existing registry fields rather than being hand-curated.
        """
        out = []
        rid = rule.get("id", "<unknown>")
        registry_rel = rule.get("registry_path", ".claude/patterns/agent-registry.json")
        registry_path = os.path.join(REPO_ROOT, registry_rel)
        try:
            reg = json.load(open(registry_path))
        except Exception as e:
            return [f"  [{rid}] cannot read registry {registry_rel}: {e}"]
        verdict_agents = set(reg.get("verdict_agents", []))
        recovery_forbidden = set(reg.get("recovery_forbidden", []))
        lead_orch_forbidden = set(reg.get("lead_orchestrated_forbidden", []))
        eligible = verdict_agents - recovery_forbidden - lead_orch_forbidden
        for gate in reg.get("hard_gates", []):
            agent = gate.get("agent")
            allow = set(gate.get("allow_predicates", []))
            if agent in eligible and "pass_lead_orchestrated" not in allow:
                out.append(
                    f"  [{rid}] agent {agent!r} is eligible "
                    f"(verdict_agent AND not in recovery_forbidden AND not in "
                    f"lead_orchestrated_forbidden) but allow_predicates lacks "
                    f"pass_lead_orchestrated"
                )
            if agent in lead_orch_forbidden and "pass_lead_orchestrated" in allow:
                out.append(
                    f"  [{rid}] agent {agent!r} is in lead_orchestrated_forbidden "
                    f"but allow_predicates includes pass_lead_orchestrated — "
                    f"this is a soundness regression (security-* probes touch "
                    f"live endpoints; retrospective lead attestation unsound)"
                )
        return out


    def check_aggregate_ok_predicate_doc_matches_impl(rule):
        """AOC v1.2 F8 — assert agent-registry.json's
        _aggregate_ok_accepted_predicates structured array exactly matches
        the predicate-name set called inside evaluate-hard-gate-predicates.py's
        aggregate_ok function.

        Uses an AST selector by predicate-name pattern (NOT line-number
        anchoring — closes round-3 critic concern #2). The selector finds
        ast.BoolOp(op=Or) nodes whose .values are ALL ast.Call to a Name
        matching ^(pass_|validated_|legacy_|aggregate_). Asserts EXACTLY
        ONE such BoolOp; multiple chains is a refactor signal.
        """
        import ast as _ast
        import re as _re
        out = []
        rid = rule.get("id", "<unknown>")
        registry_rel = rule.get("registry_path", ".claude/patterns/agent-registry.json")
        impl_rel = rule.get("impl_path", ".claude/scripts/evaluate-hard-gate-predicates.py")
        registry_path = os.path.join(REPO_ROOT, registry_rel)
        impl_path = os.path.join(REPO_ROOT, impl_rel)
        try:
            reg = json.load(open(registry_path))
        except Exception as e:
            return [f"  [{rid}] cannot read registry {registry_rel}: {e}"]
        declared = set(reg.get("_aggregate_ok_accepted_predicates", []))
        if not declared:
            return [
                f"  [{rid}] registry missing _aggregate_ok_accepted_predicates "
                f"field (added in AOC v1.2)"
            ]
        try:
            tree = _ast.parse(open(impl_path).read())
        except Exception as e:
            return [f"  [{rid}] cannot parse impl {impl_rel}: {e}"]
        func = next(
            (n for n in _ast.walk(tree)
             if isinstance(n, _ast.FunctionDef) and n.name == "aggregate_ok"),
            None,
        )
        if func is None:
            return [f"  [{rid}] aggregate_ok function not found in {impl_rel}"]
        pattern = _re.compile(r"^(pass_|validated_|legacy_|aggregate_)")
        matched = []
        for node in _ast.walk(func):
            if isinstance(node, _ast.BoolOp) and isinstance(node.op, _ast.Or):
                names = []
                ok = True
                for v in node.values:
                    if (
                        isinstance(v, _ast.Call)
                        and isinstance(v.func, _ast.Name)
                        and pattern.match(v.func.id)
                    ):
                        names.append(v.func.id)
                    else:
                        ok = False
                        break
                if ok and names:
                    matched.append(set(names))
        if len(matched) == 0:
            return [
                f"  [{rid}] no predicate-Or chain found in aggregate_ok "
                f"(expected exactly one BoolOp(Or) with all-pass_/validated_/"
                f"legacy_/aggregate_ Call values)"
            ]
        if len(matched) > 1:
            return [
                f"  [{rid}] {len(matched)} predicate-Or chains found in "
                f"aggregate_ok; refactor needed — the structured array can "
                f"no longer represent multiple chains"
            ]
        impl_set = matched[0]
        if impl_set != declared:
            only_decl = sorted(declared - impl_set)
            only_impl = sorted(impl_set - declared)
            out.append(
                f"  [{rid}] mismatch between registry "
                f"_aggregate_ok_accepted_predicates and impl aggregate_ok: "
                f"declared-only={only_decl}, impl-only={only_impl}"
            )
        return out


    def check_gecr_cutover_overdue(rule):
        """OARC #1468/#1456 meta-defense — warn when a GECR rule's Phase C
        cutover window has elapsed AND `flip_pr_required` is still true.

        Closes the a72d712 (#1415) / caef8ab (#1437) meta-recurrence pattern:
        "rule ships warn-only → soak window passes without follow-up →
        advisory-only carve-out becomes permanent → enforcement gap silently
        re-introduced".

        For each entry in `.claude/patterns/gecr-cutover-criteria.json`:
          - If `flip_pr_required` is false, skip (already flipped).
          - If `first_merged_at` is null, resolve via `git log` against the
            criteria file (first commit timestamp). When git is unavailable
            (CI fixture), skip silently — manual entries are also accepted.
          - Compute elapsed_days = (now - first_merged_at).days.
          - If elapsed_days > `soak_window_min_days`, emit a warning citing
            the tracker.

        Severity defaults to warn — this is observability, not a hard block;
        a deny-mode flip can be triggered by raising severity in a follow-up
        when the team consistently sees overdue entries.
        """
        out = []
        rid = rule.get("id", "<unknown>")
        criteria_rel = rule.get("criteria_path",
                                ".claude/patterns/gecr-cutover-criteria.json")
        criteria_path = os.path.join(REPO_ROOT, criteria_rel)
        if not os.path.isfile(criteria_path):
            return []  # criteria file not yet committed; soak phase hasn't started
        try:
            criteria = json.load(open(criteria_path))
        except Exception as e:
            return [f"  [{rid}] cannot read {criteria_rel}: {e}"]
        import datetime as dt
        import subprocess as sp
        now = dt.datetime.now(dt.timezone.utc)
        for rule_id, entry in (criteria.get("rules") or {}).items():
            if not entry.get("flip_pr_required"):
                continue  # Already flipped
            soak_days = int(entry.get("soak_window_min_days", 30))
            first_merged = entry.get("first_merged_at")
            if not first_merged:
                # Resolve via git log first-add timestamp of criteria file.
                try:
                    proc = sp.run(
                        ["git", "log", "--diff-filter=A", "--format=%cI",
                         "--", criteria_rel],
                        cwd=REPO_ROOT, text=True,
                        capture_output=True, timeout=10,
                    )
                    if proc.returncode == 0:
                        lines = [l for l in proc.stdout.strip().split("\n") if l]
                        if lines:
                            first_merged = lines[-1]
                except Exception:
                    continue  # Skip silently in CI/fixture contexts
            if not first_merged:
                continue
            try:
                first_dt = dt.datetime.fromisoformat(
                    first_merged.replace("Z", "+00:00")
                )
            except (TypeError, ValueError):
                continue
            if first_dt.tzinfo is None:
                first_dt = first_dt.replace(tzinfo=dt.timezone.utc)
            elapsed_days = (now - first_dt).days
            if elapsed_days > soak_days:
                tracker = entry.get("tracker", "<no tracker>")
                mode_env = entry.get("mode_env", "<no mode_env>")
                # The flip mechanism differs by gate kind: GATE_EVIDENCE_*
                # rules are declarative (durable flip = severity "block" in
                # gate-evidence-rules.json; the env var is a runtime
                # override), while CONSULTATION_DENY is a raw env check in
                # verify-recurrence-guard.py accepting "1" or "deny".
                if mode_env.startswith("GATE_EVIDENCE_"):
                    flip_how = (
                        f'set the rule\'s severity to "block" in '
                        f".claude/patterns/gate-evidence-rules.json "
                        f"(or export {mode_env}=deny)"
                    )
                else:
                    flip_how = f"export {mode_env}=1"
                out.append(
                    f"  [{rid}] GECR rule {rule_id!r} cutover OVERDUE: "
                    f"elapsed {elapsed_days}d > {soak_days}d soak window, "
                    f"flip_pr_required still true. Tracker: {tracker}. "
                    f"Either: (a) file the deny-flip PR ({flip_how} AND set "
                    f"flip_pr_required:false in {criteria_rel}), OR (b) "
                    f"extend soak_window_min_days with explicit rationale."
                )
        return out


    def check_post_completion_respawn_doc_present(rule):
        """#1275 / Group A — assert every agent with `pass_lead_orchestrated`
        in its hard_gates `allow_predicates` has a `## Post-completion re-spawn`
        section in its .md.

        Enumerated from `hard_gates` in the registry (single source of truth).
        Adding a new lead-orchestrated agent to the registry automatically
        triggers the doc requirement; F7's eligibility check ensures the
        registry list itself is complete.

        Severity is governed by the rule entry (default warn — informational
        catch for future drift; severity=block can be set if/when the doc
        contract becomes load-bearing).
        """
        out = []
        rid = rule.get("id", "<unknown>")
        registry_rel = rule.get("registry_path", ".claude/patterns/agent-registry.json")
        agents_rel = rule.get("agents_dir", ".claude/agents")
        required = rule.get("required_section", "## Post-completion re-spawn")
        registry_path = os.path.join(REPO_ROOT, registry_rel)
        agents_dir = os.path.join(REPO_ROOT, agents_rel)
        try:
            reg = json.load(open(registry_path))
        except Exception as e:
            return [f"  [{rid}] cannot read registry {registry_rel}: {e}"]
        for gate in reg.get("hard_gates", []):
            agent = gate.get("agent")
            allow = set(gate.get("allow_predicates", []))
            if "pass_lead_orchestrated" not in allow:
                continue
            if not isinstance(agent, str) or not agent:
                continue
            md_path = os.path.join(agents_dir, f"{agent}.md")
            if not os.path.isfile(md_path):
                out.append(
                    f"  [{rid}] agent {agent!r} is in hard_gates with "
                    f"pass_lead_orchestrated but {md_path} does not exist"
                )
                continue
            try:
                content = open(md_path).read()
            except Exception as e:
                out.append(f"  [{rid}] cannot read {md_path}: {e}")
                continue
            if required not in content:
                out.append(
                    f"  [{rid}] agent {agent!r} (.claude/agents/{agent}.md) "
                    f"is registered for pass_lead_orchestrated but does not "
                    f"contain a {required!r} section. Add the section "
                    f"documenting how the lead orchestrates the post-completion "
                    f"re-spawn (SOURCE_RUN_ID/SOURCE_SKILL env vars, "
                    f"write-agent-trace.sh invocation, expected verdict)."
                )
        return out


    # ---------------------------------------------------------------------------
    # #1295 PR1 — Stage B + Stage C handler functions.
    # ---------------------------------------------------------------------------

    def check_validator_integration_required(rule):
        """#1295 PR1 — assert each validator script is referenced by basename in
        EXECUTABLE CONTEXT in at least one declared integration_point.

        Per file type executable-context:
          - .json: parse JSON; for each string value, check parent_key:
              * if parent_key in declared executable_keys (e.g., 'verify')
                → executable
              * if parent_key matches state-name regex
                ^(?=.*\\d)[a-z0-9]+$ AND state_value_executable=True → executable
                (HC-PR1-1: state-registry has 111 bare-string state values
                 where parent_key is the state name like '11b'; these carry
                 python3 commands as VALUE, not under 'verify' key)
              * everything else → prose (NOT executable)
          - .sh: skip lines starting with `#` (comment lines)
          - .md: require appearance inside fenced ``` code block
          - other: full text (fallback)
        """
        import json as _json
        import re as _re
        findings = []
        rid = rule.get("id", "<unknown>")
        validators = rule.get("validators") or []
        integration_points = rule.get("integration_points") or []
        # #1307 — cardinality threshold. Default 1 preserves the original
        # "referenced in at least one place" contract; raise to 2+ to defend
        # against single-file edits silently dereferencing all hard-block
        # validators (e.g., state-registry.json line 11b chaining 2 validators).
        min_count = rule.get("minimum_integration_count", 1)
        if not validators:
            return [f"  [{rid}] no validators declared"]
        if not integration_points:
            return [f"  [{rid}] no integration_points declared"]

        state_name_re = _re.compile(r"^(?=.*\d)[a-z0-9]+$")  # HC-PR1-1

        def _normalize_ip(ip):
            """Accept string OR dict {path, executable_keys, state_value_executable}."""
            if isinstance(ip, str):
                return (ip, None, False)
            return (
                ip.get("path"),
                ip.get("executable_keys") or [],
                bool(ip.get("state_value_executable", False)),
            )

        def _executable_text(path, executable_keys, state_value_executable):
            try:
                text = open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                return ""
            if path.endswith(".json"):
                try:
                    data = _json.loads(text)
                except _json.JSONDecodeError:
                    return ""
                keys_set = set(executable_keys or [])
                buf = []
                def _walk(x, parent_key=None):
                    if isinstance(x, dict):
                        for k, v in x.items():
                            _walk(v, k)
                    elif isinstance(x, list):
                        for v in x:
                            _walk(v, parent_key)
                    elif isinstance(x, str):
                        is_exec = parent_key in keys_set
                        if not is_exec and state_value_executable and parent_key:
                            # HC-PR1-1: bare-string state value (parent_key
                            # matches state-name regex)
                            if state_name_re.match(parent_key):
                                is_exec = True
                        if is_exec:
                            buf.append(x)
                _walk(data)
                return "\n".join(buf)
            if path.endswith(".sh"):
                return "\n".join(
                    ln for ln in text.splitlines()
                    if not ln.lstrip().startswith("#"))
            if path.endswith(".md"):
                parts = []
                in_fence = False
                for ln in text.splitlines():
                    if ln.lstrip().startswith("```"):
                        in_fence = not in_fence
                        continue
                    if in_fence:
                        parts.append(ln)
                return "\n".join(parts)
            return text

        def _normalize_validator(v):
            """Accept bare string OR dict {path, required_env_prefix?}."""
            if isinstance(v, str):
                return (v, None)
            return (v.get("path"), v.get("required_env_prefix"))

        for v_entry in validators:
            v_rel, required_env_prefix = _normalize_validator(v_entry)
            if not v_rel:
                findings.append(f"  [{rid}] malformed validator entry: {v_entry!r}")
                continue
            v_path = os.path.join(REPO_ROOT, v_rel)
            if not os.path.isfile(v_path):
                findings.append(f"  [{rid}] validator script not found: {v_rel}")
                continue
            v_basename = os.path.basename(v_rel)
            referenced_in = []
            referenced_exec_texts = []  # parallel to referenced_in for prefix check
            for ip in integration_points:
                ip_rel, exec_keys, state_val_exec = _normalize_ip(ip)
                if not ip_rel:
                    continue
                ip_path = os.path.join(REPO_ROOT, ip_rel)
                if not os.path.isfile(ip_path):
                    continue
                exec_text = _executable_text(ip_path, exec_keys, state_val_exec)
                if v_basename in exec_text:
                    referenced_in.append(ip_rel)
                    referenced_exec_texts.append(exec_text)
            if len(referenced_in) < min_count:
                ip_paths = [_normalize_ip(ip)[0] for ip in integration_points]
                if not referenced_in:
                    coverage = "any of"
                else:
                    coverage = f"only {len(referenced_in)} of"
                findings.append(
                    f"  [{rid}] validator {v_rel} referenced in {coverage} "
                    f"the declared integration points ({', '.join(str(p) for p in ip_paths)}) "
                    f"in EXECUTABLE CONTEXT; minimum_integration_count={min_count}. "
                    f"#1307: distinct-file cardinality defends against single-file edits "
                    f"silently dereferencing all hard-block validators (e.g., a state-registry.json "
                    f"line stripping multiple validators in one chain). JSON values OUTSIDE "
                    f"declared executable_keys / state-value positions do NOT count (HC-PR1-1). "
                    f".sh comment-line and .md prose mentions do NOT count. Wire the validator "
                    f"in {min_count - len(referenced_in)} additional integration_point file(s) "
                    f"or remove from validators[]."
                )
                continue

            # #1272 follow-up: env-prefix sub-check. Each reference must have
            # the declared env prefix (e.g., STEP55_EVIDENCE_MODE=deny) within
            # 100 chars before the validator basename in the executable text.
            # Defends against silent rollout regression.
            if required_env_prefix:
                for ip_rel, exec_text in zip(referenced_in, referenced_exec_texts):
                    # Find each occurrence of the basename and check the
                    # preceding window for the prefix string.
                    found_with_prefix = False
                    for m in _re.finditer(_re.escape(v_basename), exec_text):
                        window = exec_text[max(0, m.start() - 100):m.start()]
                        if required_env_prefix in window:
                            found_with_prefix = True
                            break
                    if not found_with_prefix:
                        findings.append(
                            f"  [{rid}] validator {v_rel} referenced in {ip_rel} "
                            f"but missing required env prefix "
                            f"{required_env_prefix!r} within 100 chars before "
                            f"the invocation. Add the prefix (e.g., "
                            f"`{required_env_prefix} python3 .claude/scripts/{v_basename}`) "
                            f"or remove `required_env_prefix` from the rule entry."
                        )
        return findings

    def check_validator_inventory_completeness(rule):
        """#1295 PR1 — meta-rule: every disk-discovered validate-*.py MUST be
        in some `validator_integration_required` rule's validators[] OR in
        skip_validators (with category + justification, HC-PR1-3) OR have
        `# validator-class: <category>` magic header in lines 1-5.
        Closes manifest-relocation gap (#1295 concern #5).
        """
        import json as _json
        import re as _re
        import tokenize as _tokenize
        import io as _io
        findings = []
        rid = rule.get("id", "<unknown>")
        discovery_glob = rule.get("discovery_glob") or []
        if isinstance(discovery_glob, str):
            discovery_glob = [discovery_glob]
        skip_validators = rule.get("skip_validators") or {}
        valid_categories = {"cli-tool", "build-time", "test-only", "deprecated"}

        # HC-PR1-3 schema validation on skip_validators dict.
        if not isinstance(skip_validators, dict):
            return [f"  [{rid}] skip_validators must be a dict "
                    f"{{path: {{category, justification}}}}; got "
                    f"{type(skip_validators).__name__}"]
        for sv_path, sv_meta in skip_validators.items():
            if not isinstance(sv_meta, dict):
                findings.append(
                    f"  [{rid}] skip_validators[{sv_path!r}] must be a dict "
                    f"with 'category' and 'justification' fields")
                continue
            cat = sv_meta.get("category")
            just = (sv_meta.get("justification") or "").strip()
            if cat not in valid_categories:
                findings.append(
                    f"  [{rid}] skip_validators[{sv_path!r}] has category "
                    f"{cat!r}; must be in {sorted(valid_categories)}")
            if not just:
                findings.append(
                    f"  [{rid}] skip_validators[{sv_path!r}] has empty "
                    f"justification; must explain why this validator is "
                    f"exempt from the integration-required rule")

        # Discover validators on disk.
        # Round-1 critic C5 fix: normalize separators to forward slash for
        # cross-platform comparison with declared (POSIX-style) paths.
        discovered = set()
        for g in discovery_glob:
            for p in glob.glob(os.path.join(REPO_ROOT, g)):
                rel = os.path.relpath(p, REPO_ROOT).replace(os.sep, "/")
                discovered.add(rel)

        # HC-PR1-3 (round-1 critic C1 fix): magic-header MUST come from a
        # COMMENT token, not a string literal inside a docstring. Use
        # tokenize.tokenize to get only COMMENT tokens; check first 5
        # source-line region.
        magic_value_re = _re.compile(
            r"^# validator-class: (cli-tool|build-time|test-only|deprecated)\s*$"
        )
        magic_exempt = set()
        for v in discovered:
            v_path = os.path.join(REPO_ROOT, v)
            try:
                src = open(v_path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            try:
                tokens = list(_tokenize.tokenize(_io.BytesIO(src.encode()).readline))
            except (_tokenize.TokenizeError, SyntaxError, IndentationError):
                # Tokenize fails on malformed source — skip (no exemption).
                continue
            # Only consider COMMENT tokens whose start line is within first 5.
            for tok in tokens:
                if tok.type != _tokenize.COMMENT:
                    continue
                if tok.start[0] > 5:
                    break  # tokens are ordered by line; can stop early
                if magic_value_re.match(tok.string.strip()):
                    magic_exempt.add(v)
                    break

        # Read all `validator_integration_required` rules to compute the
        # declared validators set.
        rules_path = os.path.join(
            REPO_ROOT, ".claude/patterns/template-coherence-rules.json")
        declared = set()
        found_stage_b_rule = False
        try:
            rules_data = _json.load(open(rules_path))
            for r in rules_data.get("rules", []):
                if r.get("type") == "validator_integration_required":
                    found_stage_b_rule = True
                    for v in r.get("validators") or []:
                        # Accept bare string OR dict {path, ...} per
                        # #1272 follow-up schema extension.
                        if isinstance(v, str):
                            declared.add(v)
                        elif isinstance(v, dict) and v.get("path"):
                            declared.add(v["path"])
        except Exception as e:
            return findings + [
                f"  [{rid}] cannot read rules file: {e}"]

        # Round-1 critic C4 fix: explicit failure when Stage B rule is
        # absent — otherwise Stage C silently emits N false positives.
        if not found_stage_b_rule and discovered:
            findings.append(
                f"  [{rid}] no `validator_integration_required` rule "
                f"registered in {os.path.relpath(rules_path, REPO_ROOT)} — "
                f"Stage C cannot compute coverage. Ensure Stage B rule is "
                f"present (PR1 must include both rules atomically)."
            )
            return findings  # Don't compute spurious missing-list

        skip_set = set(skip_validators.keys())
        missing = discovered - declared - skip_set - magic_exempt
        for m in sorted(missing):
            findings.append(
                f"  [{rid}] validator {m} exists on disk but is not in any "
                f"`validator_integration_required` rule's validators[], not "
                f"in skip_validators (with category + justification), AND "
                f"does not have `# validator-class: <category>` magic header "
                f"in its first 5 lines. Choose one of: (a) add to a rule's "
                f"validators[]; (b) add to skip_validators dict with category "
                f"+ justification; (c) add `# validator-class: <category>` "
                f"as a comment line at the top of the file."
            )
        return findings

    def check_branch_checkout_propagation_pairing(rule):
        """Issue #1328: every fenced bash block (markdown) or shell-script
        segment that invokes `git checkout -b` MUST invoke
        `update-context-branch.sh` in the same chain. Without same-turn
        propagation, .runs/*-context.json's `branch` field stays stale
        relative to `git branch --show-current`, and resolve_active_identity
        filters out the active context — agent spawns in the gap stamp
        `degradation_reason: active_identity_unresolvable`.

        Markdown: scan `.md` files; within each fenced ```bash / ```sh
        block, find lines with `git checkout -b`; require
        `update-context-branch.sh` somewhere in the same fenced block.

        Shell (.sh): scan command-head positions line-by-line; if a line
        has `git checkout -b`, require `update-context-branch.sh` in the
        next 5 lines (covers multi-line `&&` chains).
        """
        import glob as _glob
        import re as _re
        findings = []
        rid = rule.get("id", "<unknown>")
        globs = rule.get("scan_globs", [])
        excludes = set(rule.get("exclude_paths", []))
        files: list[str] = []
        for g in globs:
            files.extend(_glob.glob(os.path.join(REPO_ROOT, g), recursive=True))
        # Normalize and dedupe
        files = sorted(set(os.path.relpath(f, REPO_ROOT) for f in files if os.path.isfile(f)))
        for f in files:
            if any(e in f for e in excludes):
                continue
            full = os.path.join(REPO_ROOT, f)
            try:
                txt = open(full).read()
            except OSError:
                continue
            if f.endswith(".md"):
                # Find ```bash ... ``` and ```sh ... ``` blocks.
                for m in _re.finditer(
                    r"```(?:bash|sh)\n(.*?)\n```", txt, _re.DOTALL
                ):
                    block = m.group(1)
                    if _re.search(
                        r"\bgit\s+checkout\s+-b\b", block
                    ):
                        if "update-context-branch.sh" not in block:
                            line_no = txt[: m.start()].count("\n") + 1
                            findings.append(_emit_finding(
                                rule,
                                f"{f}:~{line_no}: fenced bash block contains "
                                f"`git checkout -b` without sibling "
                                f"`update-context-branch.sh` (#1328 — bundle "
                                f"per .claude/patterns/branch.md)"
                            ))
            elif f.endswith(".sh"):
                lines = txt.split("\n")
                for i, line in enumerate(lines):
                    # Skip comment lines (the hook's own documentation
                    # mentions `git checkout -b` in comments).
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        continue
                    if _re.search(r"\bgit\s+checkout\s+-b\b", line):
                        # Look at the surrounding window: 1 line before,
                        # 5 lines after (covers multi-line `&&` chain
                        # continuations and a `||` fallback line).
                        start = max(0, i - 1)
                        end = min(len(lines), i + 6)
                        window = "\n".join(lines[start:end])
                        if "update-context-branch.sh" not in window:
                            findings.append(_emit_finding(
                                rule,
                                f"{f}:{i+1}: `git checkout -b` without "
                                f"nearby `update-context-branch.sh` "
                                f"(#1328 — bundle into one chain)"
                            ))
        return findings


    def check_state_defer_verify_pairing(rule):
        """Issue #1339: every state that opts into defer_verify_when_writer in
        state-registry.json MUST have its state file's ACTIONS section invoke
        `bash .claude/scripts/lib/write-gate-artifact.sh --path <P>` for at
        least one <P> in the declared list. Without that, the chain-aware
        gate skip would never have a sibling writer to defer to, and the
        opt-in becomes a silent no-op.
        """
        findings = []
        rid = rule.get("id", "<unknown>")
        reg_path = os.path.join(REPO_ROOT, rule.get("registry_path", ""))
        skills_dir = os.path.join(REPO_ROOT, rule.get("skills_dir", ""))
        if not os.path.isfile(reg_path):
            findings.append(_emit_finding(rule, f"registry file missing: {reg_path}"))
            return findings
        if not os.path.isdir(skills_dir):
            findings.append(_emit_finding(rule, f"skills directory missing: {skills_dir}"))
            return findings
        try:
            reg = json.load(open(reg_path))
        except (OSError, json.JSONDecodeError) as e:
            findings.append(_emit_finding(rule, f"cannot parse {reg_path}: {e}"))
            return findings
        for skill, states in reg.items():
            if not isinstance(states, dict):
                continue
            for state_id, entry in states.items():
                if not isinstance(entry, dict):
                    continue
                defer = entry.get("defer_verify_when_writer")
                if not defer:
                    continue
                if not isinstance(defer, list):
                    findings.append(_emit_finding(
                        rule,
                        f"{skill}.{state_id}: defer_verify_when_writer must be a list, got {type(defer).__name__}"
                    ))
                    continue
                # Find state file. Glob `state-{state_id}-*.md` over-matches
                # ("state-8-*.md" picks up "state-8b-*.md"); filter via regex
                # requiring the immediate suffix to be `-`.
                import glob as _glob
                import re as _re
                skill_dir = os.path.join(skills_dir, skill)
                if not os.path.isdir(skill_dir):
                    findings.append(_emit_finding(
                        rule,
                        f"{skill}.{state_id}: skill directory not found at {skill_dir}"
                    ))
                    continue
                pattern = _re.compile(rf"^state-{_re.escape(state_id)}-[^.]+\.md$")
                candidates = [
                    os.path.join(skill_dir, fn)
                    for fn in os.listdir(skill_dir)
                    if pattern.match(fn)
                ]
                if not candidates:
                    findings.append(_emit_finding(
                        rule,
                        f"{skill}.{state_id} declares defer_verify_when_writer={defer} "
                        f"but no state file at {skill_dir}/state-{state_id}-*.md"
                    ))
                    continue
                # Read the state file content
                try:
                    txt = open(candidates[0]).read()
                except OSError as e:
                    findings.append(_emit_finding(
                        rule,
                        f"{skill}.{state_id}: cannot read {candidates[0]}: {e}"
                    ))
                    continue
                # Require write-gate-artifact.sh --path <P> for at least one P
                # in the defer list. Conservative match — exact path string.
                ok = False
                for p in defer:
                    if "write-gate-artifact.sh" in txt and f"--path {p}" in txt:
                        ok = True
                        break
                if not ok:
                    findings.append(_emit_finding(
                        rule,
                        f"{skill}.{state_id} declares defer_verify_when_writer={defer} "
                        f"but {os.path.relpath(candidates[0], REPO_ROOT)} ACTIONS has no "
                        f"`bash .claude/scripts/lib/write-gate-artifact.sh --path <P>` "
                        f"for any P in the list"
                    ))
        return findings


    def _fnmatch_module(basename, pattern):
        """Case-sensitive fnmatch — supports both literal names ("__init__.py")
        and globs ("test_*.py"). Used by excluded_basenames so test fixture
        files inside lib/ are filtered from enumeration without naming each."""
        import fnmatch as _fnmatch
        return _fnmatch.fnmatchcase(basename, pattern)


    def _check_python_pragma(file_path, pragma_re, max_top_lines=50):
        """Scan top of a .py file for a regex-matched pragma (e.g.,
        `# coherence-allow: not-reusable: <reason>`).

        #1300 Python-native pragma scanner — distinct from `_parse_pragmas`
        (HTML-comment template, used in markdown) and `_pragma_in_window`
        (substring-only, used in bash_hook check). Anchored to top-of-file
        (first `max_top_lines`) so the pragma must be a deliberate module-level
        annotation, not buried mid-function.
        """
        import re as _re
        try:
            with open(file_path, encoding="utf-8") as f:
                head = "".join(f.readlines()[:max_top_lines])
        except OSError:
            return False
        return bool(_re.search(pragma_re, head))


    def _extract_module_precise_stack_scopes(readme_path):
        """Parse a Stack Knowledge README and return module names from
        `stack_scope: scripts/lib/<module>` entries.

        #1300 — directory-level entries (`stack_scope: scripts/lib`) are
        DELIBERATELY rejected to defeat the grandfather clause where 3 such
        entries (image-evidence-provenance-phash, schema-version-run-id-binding,
        canonical-writer-policy-pattern) would otherwise nullify per-helper
        coverage assertions. New entries MUST be module-precise.
        """
        import re as _re
        if not os.path.isfile(readme_path):
            return set()
        try:
            with open(readme_path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return set()
        # Match exactly `stack_scope: scripts/lib/<module>` — the trailing
        # word boundary plus character-class rejects bare `scripts/lib` and
        # `scripts/lib/` (no module). Module name pattern matches Python
        # identifier convention.
        return set(_re.findall(r"stack_scope:\s*scripts/lib/([a-zA-Z][\w_-]+)", text))


    def check_lib_helper_stack_knowledge_required(rule):
        """#1300 — every public function in lib/*.py with >= caller_threshold
        production callers must have a Stack Knowledge entry in lib/README.md
        with module-precise stack_scope, OR the helper module must declare
        `# coherence-allow: not-reusable: <reason>` at module top.

        Pattern modelled on check_discover_consumers (regex-grep + cardinality)
        + check_must_contain_section (trigger-pattern). Extended with:
          - Python AST-style public-function detection (`^def [a-zA-Z]\\w*\\(`)
          - Pragma escape hatch (Python comment, not HTML) via _check_python_pragma
          - Authoritative-source filter (lib/README.md only — not all Stack
            Knowledge surfaces) to avoid false coverage from unrelated stack files
          - Exact stack_scope match (rejects substring/prefix collisions like
            `validate_evidence` vs `validate_evidence_coverage`)
          - Allowed-extension scope (default .py + .md) to avoid path-string
            false positives in JSON/SH files
        """
        import glob as _glob
        import re as _re
        findings = []
        rid = rule.get("id", "<unknown>")
        glob_pattern = rule.get("enumeration_glob", "")
        # excluded_basenames accepts both literal names and fnmatch globs
        # (e.g. "test_*.py", "*_test.py") so test fixtures inside lib/ — like
        # `.claude/scripts/lib/test_decompose_bash_chain.py` — are filtered out
        # of enumeration without each being named explicitly.
        excluded_basenames = list(rule.get("excluded_basenames", ["__init__.py", "test_*.py", "*_test.py"]))
        consumption_patterns = rule.get("consumption_patterns", [])
        caller_threshold = rule.get("caller_threshold", 2)
        auth_source = rule.get("authoritative_source", "")
        allowed_ext = tuple(rule.get("allowed_extensions", [".py", ".md"]))
        pragma_obj = rule.get("pragma") or {}
        pragma_template = pragma_obj.get("comment_template", "")

        if not glob_pattern:
            return [f"  [{rid}] enumeration_glob is required"]
        if not consumption_patterns:
            return [f"  [{rid}] consumption_patterns is required"]
        if not auth_source:
            return [f"  [{rid}] authoritative_source is required"]
        if not pragma_template:
            return [f"  [{rid}] pragma.comment_template is required"]

        try:
            pragma_re = _re.compile(pragma_template)
        except _re.error as exc:
            return [f"  [{rid}] invalid pragma.comment_template regex: {exc}"]

        # Coverage source — only the authoritative file counts (not all
        # iter_stack_knowledge_files() outputs). Parses module-precise entries;
        # directory-level entries (stack_scope: scripts/lib) intentionally
        # don't grandfather, per the design.
        auth_path = os.path.join(REPO_ROOT, auth_source)
        covered_modules = _extract_module_precise_stack_scopes(auth_path)

        helper_files = sorted(_glob.glob(os.path.join(REPO_ROOT, glob_pattern)))

        for helper_path in helper_files:
            basename = os.path.basename(helper_path)
            if any(_fnmatch_module(basename, pat) for pat in excluded_basenames):
                continue
            module_name = basename[:-3] if basename.endswith(".py") else basename

            # Pragma scan — module declares it's deliberately not reusable.
            if _check_python_pragma(helper_path, pragma_re):
                continue

            # Public-function detection — must have at least one `def public(`.
            try:
                with open(helper_path, encoding="utf-8", errors="ignore") as f:
                    source = f.read()
            except OSError:
                continue
            public_funcs = _re.findall(
                r"^def ([a-zA-Z][\w_]*)\s*\(", source, _re.MULTILINE
            )
            if not public_funcs:
                continue

            # Caller counting — narrow consumption_patterns + extension filter
            # + per-pattern excluded_paths. Excluded_paths support `<module>`
            # substitution so the helper file itself can be excluded
            # (otherwise self-`import` matches inflate the count).
            caller_files = set()
            search_root = os.path.join(REPO_ROOT, ".claude")
            for pat_obj in consumption_patterns:
                template = pat_obj.get("pattern_template", "")
                excluded = pat_obj.get("excluded_paths", []) or []
                excluded_subst = [
                    pe.replace("<module>", module_name) for pe in excluded
                ]
                concrete = template.replace("<module>", _re.escape(module_name))
                try:
                    pattern = _re.compile(concrete)
                except _re.error:
                    continue
                for root, dirs, files in os.walk(search_root):
                    # Prune by directory glob substrings
                    pruned = []
                    for d in list(dirs):
                        rel_d = os.path.relpath(os.path.join(root, d), REPO_ROOT)
                        if any(_path_glob_match(rel_d, ex) for ex in excluded_subst):
                            pruned.append(d)
                    for d in pruned:
                        dirs.remove(d)
                    for fn in files:
                        if not fn.endswith(allowed_ext):
                            continue
                        full = os.path.join(root, fn)
                        rel = os.path.relpath(full, REPO_ROOT)
                        if any(_path_glob_match(rel, ex) for ex in excluded_subst):
                            continue
                        try:
                            with open(full, encoding="utf-8", errors="ignore") as f:
                                text = f.read()
                        except OSError:
                            continue
                        if pattern.search(text):
                            caller_files.add(rel)

            # Coverage decision: ≥threshold callers AND no module-precise entry
            if len(caller_files) >= caller_threshold and module_name not in covered_modules:
                # Sample up to 3 caller files for the finding message — gives
                # the author a concrete starting point without dumping the
                # full set into the linter output.
                sample_callers = ", ".join(sorted(caller_files)[:3])
                more = f" (+ {len(caller_files) - 3} more)" if len(caller_files) > 3 else ""
                findings.append(_emit_finding(
                    rule,
                    f"helper {module_name} ({basename}) has {len(caller_files)} "
                    f"production callers (>= {caller_threshold}: {sample_callers}{more}) "
                    f"but lacks a module-precise Stack Knowledge entry in {auth_source}. "
                    f"Either: (a) add an entry with `stack_scope: scripts/lib/{module_name}` "
                    f"and `composite_identity` + `fix_template` per the README schema; "
                    f"OR (b) add `# coherence-allow: not-reusable: <reason>` "
                    f"to the top of {basename} (use only when the helper is intentionally "
                    f"single-callsite by design). Directory-level "
                    f"`stack_scope: scripts/lib` entries do NOT count — they were the "
                    f"original gap that prompted #1300."
                ))
        return findings


    def _path_glob_match(rel_path, pattern):
        """Substring match for path glob patterns. `**` is treated as wildcard."""
        # Convert the simplified glob to a substring-friendly check. We don't
        # need fnmatch's full glob semantics; the patterns we accept are
        # things like `**/tests/**`, `**/test_*.py`, `**/*_test.py`,
        # `.claude/scripts/lib/<already-substituted>.py`.
        import fnmatch as _fnmatch
        # Strip leading `**/` for matching against arbitrary depths.
        if pattern.startswith("**/"):
            pat = pattern[3:]
            # Match if any path component matches
            if _fnmatch.fnmatch(rel_path, "*/" + pat) or _fnmatch.fnmatch(rel_path, pat):
                return True
            # Also match if the pattern's directory part is anywhere in path
            return pat.rstrip("/").rstrip("*").rstrip("/") in rel_path
        return _fnmatch.fnmatch(rel_path, pattern)


    def check_claim_must_cite_existing_rule_id(rule):
        """#1261 — Catch false coherence-rule claims.

        Scans files matching `scan_globs` for trigger phrases (e.g.,
        'coherence rule pins X') and requires a co-occurring rule_id citation
        within `window_chars` that resolves to an existing entry in
        `allowed_rule_ids_source` (default: `template-coherence-rules.json`
        rules[*].id).

        Rule shape:
          {
            "id": "<rule_id>",
            "type": "claim_must_cite_existing_rule_id",
            "severity": "warn",  # permanent during rollout per round-2 critic
            "scan_globs": [".claude/**/*.md"],
            "claim_patterns": ["coherence (linter )?rule (pins|binds)\\\\b", ...],
            "citation_pattern": "`([a-z][a-z0-9-]+)`|rule_id:\\\\s*([a-z][a-z0-9-]+)",
            "window_chars": 200,
            "allowed_rule_ids_source": ".claude/patterns/template-coherence-rules.json#rules[*].id"
          }

        Why this rule exists:
        - The original false claim 'coherence rule pins them' / 'coherence
          linter rule pins all three to match' (in scaffold-images-spec.json)
          declared a non-existent coherence rule.
        - This rule catches the antipattern's recurrence: any future prose
          asserting a coherence rule pins X without a backtick-quoted rule_id
          (or `rule_id: <id>` label) that resolves to a real rules[*].id
          will fire as a warning.

        Conservative semantics:
        - Trigger pattern match is broad (`pins\\b` / `binds\\b`); citation_pattern
          is also broad (any `[a-z][a-z0-9-]+` backtick-quoted token).
        - Citation candidates are validated against the canonical source list
          (ID resolution); unresolved candidates fail.
        - severity=warn permanent because legitimate prose discussing
          coherence-rule architecture can use the trigger phrasing without
          intent to claim a specific rule. Promote to block once 1-2 cycles
          confirm zero false-positives.
        """
        out = []
        rid = rule.get("id", "<unknown>")
        scan_globs = rule.get("scan_globs") or []
        claim_patterns_raw = rule.get("claim_patterns") or []
        citation_pattern_raw = rule.get("citation_pattern") or r"`([a-z][a-z0-9-]+)`|rule_id:\s*([a-z][a-z0-9-]+)"
        window_chars = int(rule.get("window_chars") or 200)
        allowed_source = rule.get("allowed_rule_ids_source") or ".claude/patterns/template-coherence-rules.json#rules[*].id"
        exclude_globs = rule.get("exclude_globs") or []

        if not scan_globs or not claim_patterns_raw:
            return out

        try:
            claim_compiled = [re.compile(p) for p in claim_patterns_raw]
            citation_compiled = re.compile(citation_pattern_raw)
        except re.error as e:
            out.append(f"  [{rid}] invalid regex: {e}")
            return out

        # Resolve allowed rule ids from canonical source
        src_path = allowed_source.split("#")[0]
        src_full = os.path.join(REPO_ROOT, src_path)
        allowed_ids = set()
        try:
            canonical = json.load(open(src_full))
            for r in canonical.get("rules", []):
                if isinstance(r, dict) and r.get("id"):
                    allowed_ids.add(r["id"])
        except Exception as e:
            out.append(f"  [{rid}] cannot read allowed_rule_ids_source {src_path}: {e}")
            return out

        import fnmatch as _fnmatch
        def _excluded(rel_path):
            for g in exclude_globs:
                if _fnmatch.fnmatch(rel_path, g):
                    return True
            return False

        id_re = re.compile(r"^[a-z][a-z0-9-]+$")
        for glob_pat in scan_globs:
            full_glob = os.path.join(REPO_ROOT, glob_pat)
            for fpath in sorted(glob.glob(full_glob, recursive=True)):
                rel = os.path.relpath(fpath, REPO_ROOT)
                if _excluded(rel):
                    continue
                try:
                    text = open(fpath, encoding="utf-8").read()
                except (OSError, UnicodeDecodeError):
                    continue
                for cp in claim_compiled:
                    for m in cp.finditer(text):
                        start = max(0, m.start() - window_chars)
                        end = min(len(text), m.end() + window_chars)
                        window = text[start:end]
                        cited_ids = set()
                        for cit_match in citation_compiled.finditer(window):
                            for g in cit_match.groups():
                                if g and id_re.fullmatch(g):
                                    cited_ids.add(g)
                        if not cited_ids or not (cited_ids & allowed_ids):
                            ln = text.count("\n", 0, m.start()) + 1
                            out.append(
                                f"  [{rid}] {rel}:{ln} claim '{m.group(0)}' has no citation resolving "
                                f"to an existing rule (citations found: {sorted(cited_ids) or 'none'}; "
                                f"allowed: see {allowed_source})"
                            )
        return out


    def check_hook_bypass_manifest_completeness(rule):
        """#1349 + #1350: every entry in declared bypass manifests must have
        ALL required_fields populated, with category in valid_categories.
        Mirrors the validator_inventory_completeness skip_validators
        schema-validation pattern.
        """
        findings = []
        manifests = rule.get("manifests", [])
        for mdef in manifests:
            mpath = mdef.get("path", "")
            entries_field = mdef.get("entries_field", "")
            required_fields = mdef.get("required_fields", [])
            valid_categories = set(mdef.get("valid_categories", []))
            full = os.path.join(REPO_ROOT, mpath)
            if not os.path.isfile(full):
                findings.append(_emit_finding(rule, f"manifest missing: {mpath}"))
                continue
            try:
                m = json.load(open(full))
            except (OSError, json.JSONDecodeError) as e:
                findings.append(_emit_finding(rule, f"manifest parse error ({mpath}): {e}"))
                continue
            entries = m.get(entries_field, [])
            if not isinstance(entries, list):
                findings.append(_emit_finding(rule,
                    f"{mpath}: top-level field '{entries_field}' must be an "
                    f"array, got {type(entries).__name__}"))
                continue
            for i, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    findings.append(_emit_finding(rule,
                        f"{mpath}.{entries_field}[{i}]: must be an object, "
                        f"got {type(entry).__name__}"))
                    continue
                for fname in required_fields:
                    val = entry.get(fname)
                    if val is None or (isinstance(val, str) and not val.strip()):
                        findings.append(_emit_finding(rule,
                            f"{mpath}.{entries_field}[{i}]: required field "
                            f"'{fname}' missing or empty"))
                if "category" in required_fields:
                    cat = entry.get("category")
                    if cat is not None and cat not in valid_categories:
                        findings.append(_emit_finding(rule,
                            f"{mpath}.{entries_field}[{i}]: category={cat!r} "
                            f"not in valid_categories={sorted(valid_categories)}"))
        return findings


    def check_hook_silent_skip_friction_pairing(rule):
        """#1349 + #1350: every `exit 0` / `sys.exit(0)` in a PreToolUse hook
        must be paired with a friction-log call within lookback_lines preceding
        lines, OR carry a `# friction-skip: <reason>` pragma on same/preceding
        line. Modeled on check_branch_checkout_propagation_pairing
        (line-by-line scan with window) and check_bash_hook_write_operator_binding
        (pragma suppression).
        """
        findings = []
        rid = rule.get("id", "<unknown>")
        scan_glob = rule.get("scan_glob", "")
        exclude_paths = set(rule.get("exclude_paths", []))
        exit_pattern = rule.get("exit_pattern", "")
        friction_call_pattern = rule.get("friction_call_pattern", "")
        lookback = rule.get("lookback_lines", 10)
        pragma = rule.get("pragma", "# friction-skip:")
        try:
            exit_re = re.compile(exit_pattern)
        except re.error as exc:
            return [f"  [{rid}] invalid exit_pattern regex: {exc}"]
        try:
            friction_re = re.compile(friction_call_pattern)
        except re.error as exc:
            return [f"  [{rid}] invalid friction_call_pattern regex: {exc}"]
        files = sorted(glob.glob(os.path.join(REPO_ROOT, scan_glob)))
        for full in files:
            rel = os.path.relpath(full, REPO_ROOT)
            if rel in exclude_paths:
                continue
            try:
                with open(full, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                continue
            lines = text.split("\n")
            for i, line in enumerate(lines):
                # Skip pure comment lines as match candidates so a comment
                # mentioning "exit 0" doesn't false-match.
                if line.lstrip().startswith("#"):
                    continue
                if not exit_re.search(line):
                    continue
                # Pragma on same line.
                if pragma in line:
                    continue
                # Pragma on directly preceding line.
                if i > 0 and pragma in lines[i - 1]:
                    continue
                # Friction-call within lookback window (preceding `lookback`
                # lines, NOT including the exit line itself).
                start = max(0, i - lookback)
                window = "\n".join(lines[start:i])
                if friction_re.search(window):
                    continue
                findings.append(_emit_finding(rule,
                    f"{rel}:{i+1}: `{line.strip()}` is an unfrictioned silent "
                    f"skip — add a `_write_hook_friction \"...\"` call within "
                    f"{lookback} preceding lines OR annotate with "
                    f"`{pragma} <reason>` on this or the prior line"))
        return findings


    def check_provenance_aware_runs_read(rule):
        """Flag .runs/ reads in production code that lack runs_reader.* call
        or a # scope: / pragma annotation. (#1437/#1417 — provenance-blind
        filter anti-pattern class.)

        Inverted matching: require BOTH a positive read-pattern (open(),
        json.load(), glob.glob, .open(), .read_text, cat, < "...") AND a
        .runs/<name>.<ext> path on the same line, AND no provenance-aware
        marker. Skip pure-comment lines and docstring interiors. Allowlist
        suppresses known-pending production sites during soak.
        """
        out = []
        scan_glob_csv = rule.get("scan_glob", "")
        allowlist_path = rule.get("allowlist_path", "")
        pragma = rule.get("pragma", "# coherence-allow: provenance-blind-read")

        allowlist_set = set()
        if allowlist_path:
            try:
                allowed = json.load(open(os.path.join(REPO_ROOT, allowlist_path))).get("allowed", [])
                allowlist_set = set(allowed)
            except (OSError, json.JSONDecodeError):
                pass

        naked_re = re.compile(r"\.runs/[A-Za-z0-9_./-]+\.(jsonl?|md|txt)")
        read_re = re.compile(
            r"(?:\bopen\s*\(|json\.load\s*\(|glob\.glob\s*\(|"
            r"\.read_text\s*\(|\.read_bytes\s*\(|\.readlines\s*\(|"
            r"\.open\s*\(|\bcat\s+|<\s*\")"
        )
        proof_markers = [
            "runs_reader.",
            "discover_current_run_id",
            "read_jsonl",
            "read_context_files",
            "read_git_log",
            "scope=current-run",
            "scope=cross-run-by-design",
            "# scope:",
        ]

        for glob_pattern in [g.strip() for g in scan_glob_csv.split(",") if g.strip()]:
            for path in glob.iglob(os.path.join(REPO_ROOT, glob_pattern), recursive=True):
                rel_path = os.path.relpath(path, REPO_ROOT)
                if rel_path in allowlist_set:
                    continue
                # Exclude tests by convention — tests legitimately exercise
                # .runs/ I/O as part of their fixtures and assertions.
                if "/tests/" in rel_path or rel_path.endswith("_test.py"):
                    continue
                try:
                    content = open(path).read()
                except OSError:
                    continue
                in_docstring = False
                for line_idx, line in enumerate(content.splitlines(), 1):
                    if line.count('"""') % 2 == 1 or line.count("'''") % 2 == 1:
                        in_docstring = not in_docstring
                        continue
                    if in_docstring:
                        continue
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        continue
                    if not naked_re.search(line):
                        continue
                    if not read_re.search(line):
                        continue
                    if pragma in line:
                        continue
                    if any(m in line for m in proof_markers):
                        continue
                    out.append(_emit_finding(
                        rule,
                        f"{rel_path}:{line_idx}: provenance-blind .runs/ read — "
                        f"use runs_reader.* helpers or add `{pragma}` with a rationale"
                    ))
        return out


    def check_cross_run_channel_exemption_pairing(rule):
        """For each entry in cross-run-channels.json, assert the path is NOT in
        lifecycle-init.sh STALE_ARTIFACTS (which would delete it across runs).

        Cross-run-by-design files must survive STALE_ARTIFACTS sweep. fix-ledger
        is the canonical exception: it IS in STALE_ARTIFACTS (per-run cleared)
        but is read across STATE transitions within one run, hence still
        legitimately scope=cross-run-by-design. Treat as exempt when the entry
        carries `transient_cross_state: true`.
        """
        out = []
        channels_path = rule.get("channels_path", ".claude/patterns/cross-run-channels.json")
        lifecycle_path = rule.get("lifecycle_path", ".claude/scripts/lifecycle-init.sh")

        try:
            channels = json.load(open(os.path.join(REPO_ROOT, channels_path))).get("channels", {})
        except (OSError, json.JSONDecodeError) as e:
            out.append(_emit_finding(rule, f"channels registry unreadable: {e}"))
            return out

        try:
            lifecycle_content = open(os.path.join(REPO_ROOT, lifecycle_path)).read()
        except OSError as e:
            out.append(_emit_finding(rule, f"lifecycle-init.sh unreadable: {e}"))
            return out

        stale_section_match = re.search(
            r"STALE_ARTIFACTS=\((.*?)\)", lifecycle_content, re.DOTALL
        )
        stale_list = stale_section_match.group(1) if stale_section_match else ""

        for channel_name, entry in channels.items():
            if entry.get("transient_cross_state"):
                continue  # explicitly opted into per-run cleanup
            for path in entry.get("paths", []):
                basename = os.path.basename(path)
                if basename in stale_list:
                    out.append(_emit_finding(
                        rule,
                        f"cross-run channel '{channel_name}' path '{path}' is in "
                        f"lifecycle-init.sh STALE_ARTIFACTS — would be deleted on "
                        f"next skill entry, breaking cross-run semantics. "
                        f"Either remove from STALE_ARTIFACTS or set "
                        f"`transient_cross_state: true` on the channel entry."
                    ))
        return out


    def check_prose_gate_annotation(rule):
        """#1434 — caps imperatives near toolchain references in state files
        must carry a `<!-- prose-gate:<gate_id> -->` annotation matching an
        entry in prose-gates.json, OR a sanctioned `<!-- prose-only-OK:
        ≥ 80 chars rationale -->` waiver. Closes the silent-bypass class
        where a state file's prose gate has no machine-checkable enforcement.
        """
        findings = []
        registry_path = rule.get("registry_path", "")
        scan_globs = rule.get("scan_globs", []) or []
        try:
            imperative_re = re.compile(rule.get("imperative_pattern", ""))
            toolchain_re = re.compile(rule.get("toolchain_pattern", ""))
            annotation_re = re.compile(rule.get("annotation_pattern", ""))
            waiver_re = re.compile(rule.get("waiver_pattern", ""))
        except re.error as exc:
            return [_emit_finding(rule, f"invalid regex: {exc}")]
        proximity = int(rule.get("proximity_lines", 8))
        # Load known gate ids from the registry to validate annotation suffixes.
        valid_gate_ids: set[str] = set()
        registry_abs = os.path.join(REPO_ROOT, registry_path)
        if os.path.isfile(registry_abs):
            try:
                reg = json.load(open(registry_abs))
                valid_gate_ids = {g.get("gate_id", "") for g in reg.get("gates", []) if g.get("gate_id")}
            except (OSError, json.JSONDecodeError):
                pass
        annotation_id_re = re.compile(r"<!--\s*prose-gate:([a-z][a-z0-9_-]+)\s*-->")
        for glob_pat in scan_globs:
            for path in sorted(glob.glob(os.path.join(REPO_ROOT, glob_pat), recursive=True)):
                rel = os.path.relpath(path, REPO_ROOT)
                try:
                    lines = open(path, encoding="utf-8").read().splitlines()
                except OSError:
                    continue
                for i, line in enumerate(lines):
                    if not imperative_re.search(line):
                        continue
                    start = max(0, i - proximity)
                    end = min(len(lines), i + proximity + 1)
                    window = "\n".join(lines[start:end])
                    if not toolchain_re.search(window):
                        continue
                    if waiver_re.search(window):
                        continue
                    m = annotation_id_re.search(window)
                    if m:
                        anno_id = m.group(1)
                        if valid_gate_ids and anno_id not in valid_gate_ids:
                            findings.append(_emit_finding(rule,
                                f"{rel}:{i+1}: prose-gate annotation references "
                                f"gate_id={anno_id!r} not in prose-gates.json"))
                        continue
                    findings.append(_emit_finding(rule,
                        f"{rel}:{i+1}: caps imperative `{line.strip()[:80]}` "
                        f"within {proximity} lines of toolchain reference but no "
                        f"`<!-- prose-gate:<id> -->` annotation or waiver found"))
        return findings


    def check_prose_gates_align_with_state_registry(rule):
        """#1434 — every prose-gates.json gate's scope.skill + scope.state_id
        must resolve to a state-registry.json state (or '*' for cross-skill /
        cross-state gates). Catches the round-1 critic correction class where
        a gate names a state that does not exist (e.g., bootstrap.3a vs
        verify.3a for Stage 0).
        """
        findings = []
        registry_path = rule.get("registry_path", "")
        state_registry_path = rule.get("state_registry_path", "")
        registry_abs = os.path.join(REPO_ROOT, registry_path)
        state_reg_abs = os.path.join(REPO_ROOT, state_registry_path)
        if not os.path.isfile(registry_abs):
            return [_emit_finding(rule, f"registry missing: {registry_path}")]
        if not os.path.isfile(state_reg_abs):
            return [_emit_finding(rule, f"state-registry missing: {state_registry_path}")]
        try:
            reg = json.load(open(registry_abs))
            state_reg = json.load(open(state_reg_abs))
        except (OSError, json.JSONDecodeError) as e:
            return [_emit_finding(rule, f"parse error: {e}")]
        for gate in reg.get("gates", []) or []:
            gate_id = gate.get("gate_id", "<unknown>")
            scope = gate.get("scope", {}) or {}
            skill = scope.get("skill")
            state_id = scope.get("state_id")
            if not skill or not state_id:
                findings.append(_emit_finding(rule,
                    f"gate {gate_id}: scope.skill or scope.state_id missing"))
                continue
            if skill == "*":
                continue  # Cross-skill gate; nothing to verify.
            if skill not in state_reg:
                findings.append(_emit_finding(rule,
                    f"gate {gate_id}: skill {skill!r} not in state-registry.json"))
                continue
            if state_id != "*" and str(state_id) not in (state_reg.get(skill) or {}):
                findings.append(_emit_finding(rule,
                    f"gate {gate_id}: state {skill}.{state_id} not in state-registry.json"))
        return findings


    def check_route_resolution_canonical_source(rule):
        """#1450 gaps 1-3 — Python scripts that resolve page-name → route-path
        must source page enumeration from derive_pages.py.

        Pragmatic detection: rule fires when a .py file under scan_corpus
        contains a glob.glob() pattern referencing both `src/app` and `page.tsx`
        AND does not import from the canonical module (`derive_pages`). This
        catches reimplementations of route-shape resolution (the auditor vs
        emit-sitemap drift class). Pure AST detection is deferred — pragmatic
        regex is the chosen tradeoff to ship the prevention guard now.
        """
        import glob as _glob
        import re as _re
        findings = []
        rid = rule.get("id", "<unknown>")
        scan_corpus = rule.get("scan_corpus", [])
        canonical_mod = rule.get("canonical_module", "derive_pages")
        trigger_pattern = rule.get("trigger_pattern", "")
        exempt_paths = rule.get("exempt_paths", [])

        if not scan_corpus:
            return [f"  [{rid}] scan_corpus is required"]
        if not trigger_pattern:
            return [f"  [{rid}] trigger_pattern is required"]
        try:
            trigger_re = _re.compile(trigger_pattern)
        except _re.error as exc:
            return [f"  [{rid}] invalid trigger_pattern regex: {exc}"]

        exempt = set()
        for pat in exempt_paths:
            for p in _glob.glob(os.path.join(REPO_ROOT, pat), recursive=True):
                exempt.add(os.path.normpath(p))

        # Import detection — accept any form referencing the canonical module
        # name as a top-level symbol: `from derive_pages import X`,
        # `from .derive_pages import X`, `from foo.derive_pages import X`,
        # `import derive_pages`, `import foo.derive_pages`.
        import_re = _re.compile(
            rf"^\s*(from\s+[\w.]*\b{_re.escape(canonical_mod)}\b|"
            rf"import\s+[\w.]*\b{_re.escape(canonical_mod)}\b)",
            _re.MULTILINE,
        )

        for pat in scan_corpus:
            for path in sorted(_glob.glob(os.path.join(REPO_ROOT, pat), recursive=True)):
                norm = os.path.normpath(path)
                if norm in exempt:
                    continue
                try:
                    with open(path, encoding="utf-8", errors="ignore") as fh:
                        source = fh.read()
                except OSError:
                    continue
                if trigger_re.search(source) and not import_re.search(source):
                    rel = os.path.relpath(path, REPO_ROOT)
                    findings.append(_emit_finding(rule,
                        f"{rel}: globs src/app/**/page.tsx without importing from "
                        f"{canonical_mod} — route-shape resolution must source from "
                        f"the canonical helper to prevent the auditor/emitter drift "
                        f"class (#1450 gaps 1-3)"))
        return findings


    def check_gate_verdict_evidence_coverage(rule):
        """GECR #1473+#1470 — Structural-shape gate-keeper checks must be
        covered by a rule in gate-evidence-rules.json OR carry an explicit
        evidence_check_intentionally_structural annotation.

        Prevents meta-level structural-proxy regression: a future gate-keeper
        check that uses test -f / test -d / grep -E.*href / grep -c (the
        gameable shapes #1473 + #1470 closed) silently passes lint unless
        the author registers a rule or annotates the exemption.

        Mirrors `check_route_resolution_canonical_source` pattern (#1460).
        Defensive: fails loud on malformed registry shape instead of stack
        trace (Plan-Agent-A Open Risk 1). Annotation-spelling validation
        via `valid_annotations` closed enum (Plan-Agent-B Concern 18).
        """
        import glob as _glob
        import json as _json
        import re as _re
        findings = []
        rid = rule.get("id", "<unknown>")
        scan_corpus = rule.get("scan_corpus", [])
        rules_registry_path = rule.get("rules_registry", "")
        trigger_pattern = rule.get("trigger_pattern", "")
        exempt_paths = rule.get("exempt_paths", [])
        valid_annotations = rule.get(
            "valid_annotations",
            ["evidence_check_intentionally_structural"],
        )
        annotation_key = rule.get(
            "annotation_registry_key",
            "evidence_check_intentionally_structural",
        )

        if not scan_corpus:
            return [f"  [{rid}] scan_corpus is required"]
        if not rules_registry_path:
            return [f"  [{rid}] rules_registry is required"]
        if not trigger_pattern:
            return [f"  [{rid}] trigger_pattern is required"]

        try:
            trigger_re = _re.compile(trigger_pattern)
        except _re.error as exc:
            return [f"  [{rid}] invalid trigger_pattern regex: {exc}"]

        # Load registry — fail loud on parse error / missing required shape.
        # Defensive schema check (Plan-Agent-A Open Risk 1): registry MUST
        # be a dict with `rules` array. Bad shape → infrastructure finding,
        # not silent miss.
        registry_path_abs = os.path.join(REPO_ROOT, rules_registry_path)
        if not os.path.isfile(registry_path_abs):
            return [
                f"  [{rid}] rules_registry not found at {rules_registry_path}"
            ]
        try:
            with open(registry_path_abs) as fh:
                registry = _json.load(fh)
        except (OSError, _json.JSONDecodeError) as exc:
            return [
                f"  [{rid}] cannot parse rules_registry at "
                f"{rules_registry_path}: {exc}"
            ]
        if not isinstance(registry, dict) or not isinstance(
            registry.get("rules"), list
        ):
            return [
                f"  [{rid}] rules_registry malformed: missing top-level "
                f"`rules` array at {rules_registry_path}"
            ]

        # Build registered set: rule ids AND gate_ids both count as "covered"
        registered: set[str] = set()
        for r in registry.get("rules", []):
            if isinstance(r, dict):
                if r.get("id"):
                    registered.add(r["id"])
                if r.get("gate_id"):
                    registered.add(r["gate_id"])

        # Annotation registry — top-level key listing intentionally-structural
        # check identifiers (e.g., "bg2-check-7-quality"). Schema accepts both
        # bare strings and {check_id, justification} dicts (see
        # gate-evidence-rule-schema.json oneOf for evidence_check_intentionally_structural).
        annotated: set[str] = set()
        ann_list = registry.get(annotation_key, [])
        if isinstance(ann_list, list):
            for entry in ann_list:
                if isinstance(entry, str):
                    annotated.add(entry)
                elif isinstance(entry, dict):
                    cid = entry.get("check_id")
                    if isinstance(cid, str):
                        annotated.add(cid)

        # Validate annotation typos (Plan-Agent-B Concern 18): every top-level
        # key in registry that starts with "evidence_check_" must be in
        # valid_annotations. Typo produces did-you-mean output.
        for key in registry.keys():
            if not isinstance(key, str):
                continue
            if not key.startswith("evidence_check_"):
                continue
            if key not in valid_annotations:
                closest = ", ".join(valid_annotations)
                findings.append(_emit_finding(rule,
                    f"unknown annotation key '{key}' in {rules_registry_path}"
                    f" — did you mean one of: {closest}?"))

        # Scan corpus for structural-shape triggers
        exempt: set[str] = set()
        for pat in exempt_paths:
            for p in _glob.glob(os.path.join(REPO_ROOT, pat), recursive=True):
                exempt.add(os.path.normpath(p))

        for pat in scan_corpus:
            for path in sorted(_glob.glob(os.path.join(REPO_ROOT, pat), recursive=True)):
                norm = os.path.normpath(path)
                if norm in exempt:
                    continue
                try:
                    with open(path, encoding="utf-8", errors="ignore") as fh:
                        source = fh.read()
                except OSError:
                    continue

                rel = os.path.relpath(path, REPO_ROOT)
                # Walk line by line; report each match that lacks coverage
                for lineno, line in enumerate(source.splitlines(), start=1):
                    if not trigger_re.search(line):
                        continue
                    # Heuristic check identifier: derive from line text +
                    # file (e.g., "gate-keeper.md:309"). The author can
                    # register this identifier in the registry to mark it
                    # covered, OR add to evidence_check_intentionally_structural
                    # list with a justification.
                    check_id = f"{rel}:{lineno}"
                    # Coverage: any registered id appearing in the line
                    # (gate-keeper checks often inline their rule id),
                    # OR explicit annotation
                    covered = check_id in annotated or any(
                        rid_check and rid_check in line for rid_check in registered
                    )
                    if covered:
                        continue
                    findings.append(_emit_finding(rule,
                        f"{rel}:{lineno}: structural-shape check (test -f / "
                        f"test -d / grep -E.*href / grep -c) without GECR "
                        f"coverage. Add a rule to {rules_registry_path} that "
                        f"references this check's gate-id, OR add "
                        f"'{check_id}' to the {annotation_key} list in "
                        f"{rules_registry_path} with a justification."))
        return findings


    # ---------------------------------------------------------------------------
    # Cross-file rule dispatch — registry-driven with type + field validation.
    #
    # HANDLERS maps each rule type to:
    #   (handler_fn, required_keys, optional_keys, is_strict_aoc)
    #
    # At rule-load time we validate:
    #   1. type is in HANDLERS — typo'd type triggers SystemExit (return 1)
    #   2. all required keys are present — missing required triggers SystemExit
    #   3. no unknown keys (after subtracting META_KEYS) — typo'd field name
    #      triggers SystemExit
    #
    # STRICT_AOC_TYPES is derived from is_strict_aoc=True entries (replaces the
    # hardcoded set at the top of main).
    #
    # Schema errors are intentionally fatal even under --warn-only: a typo'd
    # rule key is an infrastructure error, not a coherence violation, and must
    # surface immediately. Documented in lib/linter/README.md (PR4).
    # ---------------------------------------------------------------------------
    HANDLERS = {
        "field_role_map":                   (check_field_role_map,                   {"field", "canonical_function"},                          {"consumers"},                                                False),
        "discover_consumers":               (check_discover_consumers,               {"field", "against_rule", "consumption_patterns"},        {"path_excludes"},                                            False),
        "artifact_lifecycle":               (check_artifact_lifecycle,               {"skill"},                                                set(),                                                        False),
        "verdict_vocab_consistency":        (check_verdict_vocab_consistency,        set(),                                                    {"registry_path", "agent_files_glob", "predicate_file"},      True),
        "ledger_ownership":                 (check_ledger_ownership,                 {"allowed_writers", "gated_paths"},                       set(),                                                        True),
        # Issue #1299 — gate-artifact canonical-writer enforcement. is_strict_aoc=False
        # initially (severity=warn during soak). Flips True in chore/canonical-writer-migration-deny.
        "gate_artifact_writer_enforcement": (check_gate_artifact_writer_enforcement, {"manifest_path"},                                        {"allowed_writers", "scan_corpus"},                            False),
        "consumer_coverage":                (check_consumer_coverage,                {"canonical_source", "consumers"},                        set(),                                                        True),
        # #1381 D1 — parity check across an agent family in hard_gates.
        "agent_registry_predicate_parity":  (check_agent_registry_predicate_parity,  {"family_prefix", "baseline_agent"},                      set(),                                                        True),
        # #1381 D3 — Stage 0 detector must pair its trigger with a bootstrap-verify mode skip.
        "stage_0_detector_mode_aware":      (check_stage_0_detector_mode_aware,      {"scan_glob"},                                            {"trigger_pattern", "mode_check_pattern"},                    True),
        # #1379 G1 — state-registry VERIFY blocks using d.values() against gate-stamped artifacts must use unstamped_values(d).
        "verify_d_values_against_stamped_artifact": (check_verify_d_values_against_stamped_artifact, set(),                                {"registry_path", "manifest_path"},                            False),
        # #1393 r3 Item 1 — sanctioned-manual-write markers in procedure docs.
        "hook_friction_action_type_classify": (check_hook_friction_action_type_classify, set(),                                          {"scan_globs"},                                                False),
        # #1393 r3 Item 2 — pin the .jsonl telemetry carve-out (docstring + regex paired).
        "derive_graim_manifest_carveout_pin": (check_derive_graim_manifest_carveout_pin, set(),                                          set(),                                                         True),
        # #1393 r3 Item 3 — every [audit:VERB=...] tag must use a registered verb.
        "audit_tag_verb_recognized":          (check_audit_tag_verb_recognized,         set(),                                          {"registry_path", "scan_globs"},                               False),
        # #1393 r3 Item 4 — audit-tag claims must have matching AST evidence.
        "audit_tag_claim_matches_ast":        (check_audit_tag_claim_matches_ast,       set(),                                          {"registry_path", "experiment_path", "scaffold_glob"},         False),
        # #1393 r3 Item 4 — pipeline-step cardinality consistency (prepass+merger per #1257).
        "cardinality_consistency_across_pipeline_steps": (check_cardinality_consistency_across_pipeline_steps, {"pairs"},                set(),                                                         False),
        "frontmatter_artifact_consistency": (check_frontmatter_artifact_consistency, {"schema_path", "writer"},                                {"consumers"},                                                True),
        "internal_href_validity":           (check_internal_href_validity,           set(),                                                    {"scaffold_glob", "route_owner_hints"},                       False),
        "pages_no_payload_type_exports":    (check_pages_no_payload_type_exports,    {"scope_glob"},                                           {"path_excludes", "filename_excludes", "suffix_pattern", "types_source_path"}, True),
        "artifact_transience":              (check_artifact_transience,              {"skill"},                                                {"init_script"},                                              False),
        "executor_enforcement":             (check_executor_enforcement,             set(),                                                    {"manifest_path", "hooks_dir", "agents_glob"},                False),
        "gate_evidence_escape":             (check_gate_evidence_escape,             set(),                                                    {"inventory_path", "registry_path"},                          False),
        "gate_artifact_identity":           (check_gate_artifact_identity,           {"manifest_path", "enforced_artifacts"},                  {"registry_path"},                                            False),
        "boundary_kind_required":           (check_boundary_kind_required,           {"enforced_artifacts"},                                   {"agent_files_glob", "skill_files_glob"},                     False),
        "gate_artifact_discovery":          (check_gate_artifact_discovery,          {"manifest_path"},                                        {"registry_path", "hooks_glob"},                              False),
        "must_contain_section":             (check_must_contain_section,             {"applies_to_glob", "required_section", "trigger_pattern_any"}, {"exclude_glob"},                                       False),
        # #1447 Rule D — cross-file enum-membership audit: every event in any
        # active stack frontmatter `emits_events:` MUST appear under `events:`
        # in experiment/EVENTS.yaml. No-ops on template repo (no EVENTS.yaml).
        "events_yaml_seeded_from_stack_emits_events": (check_events_yaml_seeded_from_stack_emits_events, set(), {"stack_glob", "events_yaml_path", "exclude_stack_glob"}, False),
        # #1261 — catches false coherence-rule claims (e.g. "coherence rule
        # pins all three" without a co-occurring rule_id citation that resolves
        # to a real rules[*].id). Severity warn permanent (round-2 critic
        # concern 8b25a61dd0e6: trigger pattern is intentionally broad).
        "claim_must_cite_existing_rule_id": (check_claim_must_cite_existing_rule_id, {"scan_globs", "claim_patterns"}, {"citation_pattern", "window_chars", "allowed_rule_ids_source", "exclude_globs"}, False),
        "bash_hook_write_operator_binding": (check_bash_hook_write_operator_binding, {"manifest_path", "scan_glob"},                                 {"pragma"},                                                   False),
        "markdown_cross_file_line_reference": (check_markdown_cross_file_line_reference, {"target_glob"},                                            {"pragma"},                                                   False),
        # AOC v1.2 PR6 — F7 + F8 lints.
        "lead_orchestrated_eligibility_complete": (check_lead_orchestrated_eligibility_complete, set(), {"registry_path"}, True),
        "aggregate_ok_predicate_doc_matches_impl": (check_aggregate_ok_predicate_doc_matches_impl, set(), {"registry_path", "impl_path"}, True),
        # #1275 / Group A — post-completion re-spawn doc presence.
        "post_completion_respawn_doc_present": (check_post_completion_respawn_doc_present, set(), {"registry_path", "agents_dir", "required_section"}, False),
        # OARC #1468/#1456 meta-defense — warn when GECR Phase C cutover overdue.
        "gecr_cutover_overdue": (check_gecr_cutover_overdue, set(), {"criteria_path"}, False),
        # #1295 PR1 — Stage B + Stage C validator coherence rules.
        # #1307 — minimum_integration_count is an optional cardinality
        # threshold (default 1 preserves backwards compat).
        "validator_integration_required": (
            check_validator_integration_required,
            {"validators", "integration_points"},
            {"minimum_integration_count"},
            True,  # is_strict_aoc — hard-block validators MUST stay integrated
        ),
        "validator_inventory_completeness": (
            check_validator_inventory_completeness,
            set(),
            {"discovery_glob", "skip_validators"},
            True,  # is_strict_aoc — meta-rule for hard-block validator coverage
        ),
        # #1339 — opt-in deferred VERIFY pairing. Every state with
        # defer_verify_when_writer in state-registry.json must have a
        # write-gate-artifact.sh invocation in its state file's ACTIONS.
        "state_defer_verify_pairing": (
            check_state_defer_verify_pairing,
            {"registry_path", "skills_dir"},
            set(),
            True,  # is_strict_aoc — block at lifecycle-finalize.sh:289 even under --warn-only
        ),
        # #1328 — git checkout -b must be paired with update-context-branch.sh
        # in the same Bash chain. Markdown: same fenced block. Shell: 5-line
        # window. Comment lines are skipped (the hook's own documentation
        # mentions `git checkout -b` in comments).
        "branch_checkout_propagation_pairing": (
            check_branch_checkout_propagation_pairing,
            {"scan_globs"},
            {"exclude_paths"},
            True,  # is_strict_aoc — block at lifecycle-finalize.sh:289 even under --warn-only
        ),
        # #1300 — per-helper Stack Knowledge coverage in lib/README.md.
        # Closes the must_contain_section gap (presence-of-heading) by
        # enumerating lib/*.py public functions, counting production callers
        # via narrow consumption_patterns, and asserting each multi-caller
        # helper has a module-precise stack_scope entry OR a not-reusable
        # pragma. is_strict_aoc=True so violations block under --strict-aoc.
        "lib_helper_stack_knowledge_required": (
            check_lib_helper_stack_knowledge_required,
            {"enumeration_glob", "consumption_patterns", "authoritative_source", "pragma"},
            {"caller_threshold", "excluded_basenames", "allowed_extensions"},
            True,  # is_strict_aoc — block at lifecycle-finalize.sh:289 even under --warn-only
        ),
        # #1349 + #1350 — silent-bypass class prevention. Both block under
        # --strict-aoc to prevent regression: a hook landing with an
        # unfrictioned silent exit 0 fails lifecycle-finalize.sh:289.
        "hook_bypass_manifest_completeness": (
            check_hook_bypass_manifest_completeness,
            {"manifests"},
            set(),
            True,  # is_strict_aoc — manifests are runtime-load-bearing
        ),
        "hook_silent_skip_friction_pairing": (
            check_hook_silent_skip_friction_pairing,
            {"scan_glob", "exit_pattern", "friction_call_pattern", "pragma"},
            {"exclude_paths", "lookback_lines"},
            True,  # is_strict_aoc — silent-bypass is the bug class itself
        ),
        # #1450 gaps 1-3 — route-resolution drift prevention. Fires when a .py
        # file under .claude/scripts/ globs src/app/**/page.tsx without
        # importing from derive_pages. Block under --strict-aoc.
        "route_resolution_canonical_source": (
            check_route_resolution_canonical_source,
            {"scan_corpus", "canonical_module", "trigger_pattern"},
            {"canonical_symbols", "exempt_paths"},
            True,  # is_strict_aoc — drift produces user-visible auditor/sitemap bugs
        ),
        # GECR #1473+#1470 — meta-coverage rule preventing structural-shape-as-
        # proxy regression. Scans gate-keeper.md and check-observation-artifacts.sh
        # for test -f / test -d / grep -E.*href / grep -c patterns; for each
        # match, requires either a registered gate-id in gate-evidence-rules.json
        # OR an explicit evidence_check_intentionally_structural annotation
        # entry. is_strict_aoc=False initially — soak window flips to True after
        # ≥2 real skill cycles (per #1291 convention).
        "gate_verdict_evidence_coverage": (
            check_gate_verdict_evidence_coverage,
            {"scan_corpus", "rules_registry", "trigger_pattern"},
            {"exempt_paths", "valid_annotations", "annotation_registry_key"},
            False,
        ),
        # #1437 + #1417 — provenance-blind filter class prevention.
        # Soak: is_strict_aoc=False during one PR cycle. Promote to True
        # after follow-up PRs migrate the 16 production sites listed in
        # provenance-blind-allowlist.json.
        "provenance_aware_runs_read": (
            check_provenance_aware_runs_read,
            {"scan_glob"},
            {"allowlist_path", "pragma"},
            False,
        ),
        "cross_run_channel_exemption_pairing": (
            check_cross_run_channel_exemption_pairing,
            set(),
            {"channels_path", "lifecycle_path"},
            False,
        ),
        # #1434 — prose-gate annotation: caps imperatives near toolchain refs
        # in state files must have a <!-- prose-gate:<id> --> annotation that
        # matches an entry in prose-gates.json (or a sanctioned waiver).
        "prose_gate_annotation": (
            check_prose_gate_annotation,
            {"registry_path", "scan_globs", "imperative_pattern",
             "toolchain_pattern", "annotation_pattern", "waiver_pattern"},
            {"proximity_lines"},
            False,
        ),
        # #1434 — prose-gates registry alignment: every gate's scope.skill +
        # scope.state_id must resolve to a state-registry.json state (or '*').
        "prose_gates_align_with_state_registry": (
            check_prose_gates_align_with_state_registry,
            {"registry_path", "state_registry_path"},
            set(),
            False,
        ),
    }
    META_KEYS = {"id", "type", "severity", "description", "_transitional_note", "_comment", "convention_doc"}

    # Derive STRICT_AOC_TYPES from HANDLERS — single source of truth.
    # Replaces the hardcoded set previously at the top of main(). When a new
    # handler with is_strict_aoc=True is registered, _is_aoc_finding (used for
    # --strict-aoc exit-code partitioning) automatically picks it up; no
    # second list to keep in sync.
    STRICT_AOC_TYPES = {t for t, (_h, _r, _o, is_strict) in HANDLERS.items() if is_strict}

    # Load and run cross-file rules
    if os.path.isfile(RULES_PATH):
        try:
            rules_data = json.load(open(RULES_PATH))
            rules_list = rules_data.get("rules", [])
        except (OSError, json.JSONDecodeError) as e:
            cross_file.append(f"  [framework] failed to load rules from {RULES_PATH}: {e}")
            rules_list = []

        for i, rule in enumerate(rules_list):
            rid = rule.get("id", f"#{i}")
            rtype = rule.get("type")
            if rtype not in HANDLERS:
                valid = ", ".join(sorted(HANDLERS))
                print(
                    f"verify-linter: unknown rule type {rtype!r} in rule id={rid}; valid: {valid}",
                    file=sys.stderr,
                )
                return 1
            handler, required, optional, _is_strict_aoc = HANDLERS[rtype]
            keys = set(rule.keys()) - META_KEYS
            unknown = keys - (required | optional)
            if unknown:
                print(
                    f"verify-linter: unknown field(s) {sorted(unknown)} in rule id={rid} (type={rtype}); "
                    f"valid: {sorted(required | optional)}",
                    file=sys.stderr,
                )
                return 1
            missing = required - keys
            if missing:
                print(
                    f"verify-linter: missing required field(s) {sorted(missing)} in rule id={rid} (type={rtype})",
                    file=sys.stderr,
                )
                return 1
            try:
                cross_file.extend(handler(rule))
            except Exception as e:
                cross_file.append(
                    f"  [{rid}] handler crashed: {type(e).__name__}: {e}"
                )


    # ---------------------------------------------------------------------------
    # Output: JSON or human-readable report
    # ---------------------------------------------------------------------------

    if JSON_OUT or CACHE_FILE:
        payload = {
            "uncovered": uncovered,
            "diverged": diverged,
            "unjustified_true": unjustified_true,
            "drift_declared": drift_declared,
            "cross_file_contradiction": cross_file,
            "summary": {
                "uncovered": len(uncovered),
                "diverged": len(diverged),
                "unjustified_true": len(unjustified_true),
                "drift_declared": len(drift_declared),
                "cross_file_contradiction": len(cross_file),
            },
        }
        if CACHE_FILE:
            os.makedirs(os.path.dirname(CACHE_FILE) or ".", exist_ok=True)
            with open(CACHE_FILE, "w") as f:
                json.dump(payload, f, indent=2)
        if JSON_OUT:
            print(json.dumps(payload, indent=2))

    # Human report (suppressed when JSON_OUT is set)
    if not JSON_OUT:
        print("VERIFY Linter Report")
        print("====================")
        print()

        if uncovered:
            print("UNCOVERED (artifact in postcondition but not in VERIFY):")
            for line in uncovered:
                print(line)
            print()

        if diverged:
            print("DIVERGED (state file VERIFY != registry VERIFY):")
            for line in diverged:
                print(line)
            print()

        if unjustified_true:
            print("UNJUSTIFIED_TRUE:")
            for line in unjustified_true:
                print(line)
            print()

        if drift_declared:
            print("DRIFT_DECLARED_VS_PROSE (registry declaration disagrees with state-file prose):")
            for line in drift_declared:
                print(line)
            print()

        if cross_file:
            print("CROSS_FILE_CONTRADICTION (template-coherence-rules.json violations):")
            for line in cross_file:
                print(line)
            print()

        print(
            f"Summary: {len(uncovered)} uncovered, {len(diverged)} diverged, "
            f"{len(unjustified_true)} unjustified_true, {len(drift_declared)} drift_declared, "
            f"{len(cross_file)} cross_file_contradiction"
        )

    # Exit code — layered semantics:
    #   default (no flags): any finding blocks (exit 1).
    #   --warn-only: downgrades ALL findings to warnings (exit 0).
    #   --strict-aoc: forces AOC findings (R1/R2/R3) to block regardless of
    #                 --warn-only; other findings still honor --warn-only.
    #
    # AOC findings are tagged in their message string by _emit_finding with
    # "(<rule_type>/<severity>)". Partition cross_file by presence of STRICT_AOC_TYPES.

    def _is_aoc_finding(msg):
        return any(f"({t}/" in msg for t in STRICT_AOC_TYPES)


    aoc_findings = [m for m in cross_file if _is_aoc_finding(m)]
    non_aoc_findings = (
        uncovered + unjustified_true + diverged + drift_declared +
        [m for m in cross_file if not _is_aoc_finding(m)]
    )

    should_block = False
    # AOC findings: block when not warn-only OR when strict-aoc is set.
    if aoc_findings and (not WARN_ONLY or STRICT_AOC):
        should_block = True
    # Non-AOC findings: block only when not warn-only (strict-aoc does not apply).
    if non_aoc_findings and not WARN_ONLY:
        should_block = True
    if should_block:
        return 1
    return 0
