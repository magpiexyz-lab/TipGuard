# STATE 0: SCOPE_AND_BASELINE

**PRECONDITIONS:**
- Git repository exists in working directory

**ACTIONS:**

### Scope selection

Parse `$ARGUMENTS` for an optional focus scope:

| Argument | Scope | Files scanned |
|----------|-------|---------------|
| (empty) | full | All template-source files (see canonical scope in State 1) |
| `hooks` | hooks only | `.claude/hooks/*.sh` |
| `commands` | commands only | `.claude/commands/*.md` |
| `skills` | skills only | `.claude/skills/**/state-*.md`, `.claude/skills/**/skill.yaml`, `.claude/skills/**/orchestration.json`, `.claude/skills/**/gates/*.sh` |
| `patterns` | patterns only | `.claude/patterns/**/*.md`, `.claude/patterns/*.json`, `.claude/procedures/*.md` |
| `agents` | agents only | `.claude/agents/*.md`, `.claude/agents/*.json` |
| `stacks` | stacks only | `.claude/stacks/**/*.md` |
| `scripts` | scripts only | `.claude/scripts/**/*.{sh,py}`, `scripts/**/*.{py,sh,mjs}` |

If `$ARGUMENTS` contains `--save`, set `save_manifest = true`.

### Baseline metrics

Run these commands and hold the results in working memory:

```bash
# Template-source file predicate (reused below). Includes every analysis-target
# extension across .claude/ and top-level scripts/. Excludes only build cache
# and machine-local artifacts.
TPL_FIND_ARGS='( -name *.md -o -name *.sh -o -name *.py -o -name *.json -o -name *.yaml -o -name *.mjs )'
TPL_PRUNE='-not -path *__pycache__* -not -path *worktrees* -not -path *node_modules* -not -name settings.local.json -not -name *.lock'

# File inventory by type and total lines
echo "=== File inventory ===" && \
find .claude scripts -type f -name '*.md' $TPL_PRUNE 2>/dev/null | wc -l && \
find .claude scripts -type f -name '*.sh' $TPL_PRUNE 2>/dev/null | wc -l && \
find .claude scripts -type f -name '*.py' $TPL_PRUNE 2>/dev/null | wc -l && \
find .claude scripts -type f \( -name '*.json' -o -name '*.yaml' -o -name '*.mjs' \) $TPL_PRUNE 2>/dev/null | wc -l && \
echo "=== Total lines ===" && \
find .claude scripts Makefile -type f $TPL_FIND_ARGS $TPL_PRUNE 2>/dev/null | xargs wc -l | tail -1

# Top 25 largest files (within selected scope, or all if full)
echo "=== Largest files ===" && \
find .claude scripts Makefile -type f $TPL_FIND_ARGS $TPL_PRUNE 2>/dev/null | \
  xargs wc -l | sort -rn | head -25

# Duplication signals: inline python3 one-liners in hooks (the #1 duplication source)
echo "=== Inline python3 patterns in hooks ===" && \
grep -ch 'python3 -c' .claude/hooks/*.sh 2>/dev/null | paste -d: - <(ls .claude/hooks/*.sh) | sort -rn

# Cross-file reference frequency
echo "=== Most-referenced patterns ===" && \
grep -roh '[a-z/-]*\.md' .claude/commands/ .claude/patterns/ 2>/dev/null | \
  grep -v '^$' | sort | uniq -c | sort -rn | head -15

# Hook function definitions (shared vs local)
echo "=== Hook functions ===" && \
grep -hn '^[a-z_]*()' .claude/hooks/*.sh 2>/dev/null
```

### Skill manifest (Dimension D pre-computation)

> Dimension D (Skill Architecture) runs only under `full` scope.
> If scope is not `full`, skip this section entirely.

If scope is `full`, generate `.runs/audit-skill-manifest.json`:

```bash
PAYLOAD=$(python3 -c "
import json, glob, re, os, sys
try:
    import yaml
except ImportError:
    yaml = None

manifest = {}
# 1. Read dispatch tables from command files
for cmd_file in sorted(glob.glob('.claude/commands/*.md')):
    skill = os.path.basename(cmd_file).replace('.md', '')
    # Extract state file references from dispatch table
    with open(cmd_file) as f:
        content = f.read()
    refs = re.findall(r'state-(\S+?)\.md', content)
    dispatch_ids = sorted(set(refs))

    # 1b. Read skill.yaml states list — the canonical orchestration source.
    # commands/<skill>.md is a thin lifecycle dispatcher (runs
    # lifecycle-next.sh) that no longer enumerates state IDs inline,
    # so dispatch_ids extracted above is typically empty. The authoritative
    # state list lives in skill.yaml as either a top-level `states: [...]`
    # array or, for multi-mode skills (e.g., iterate with --check / --cross),
    # under `modes.<mode>.states`. A state file is orphaned only if its
    # ID is missing from the union of all modes' states.
    yaml_states: list[str] = []
    skill_yaml = f'.claude/skills/{skill}/skill.yaml'
    if os.path.isfile(skill_yaml):
        try:
            with open(skill_yaml) as f:
                yaml_text = f.read()
            collected: list[str] = []
            if yaml is not None:
                data = yaml.safe_load(yaml_text) or {}
                if isinstance(data, dict):
                    top = data.get('states', []) or []
                    if isinstance(top, list):
                        collected.extend(str(s) for s in top)
                    modes = data.get('modes', {}) or {}
                    if isinstance(modes, dict):
                        for mode_cfg in modes.values():
                            if isinstance(mode_cfg, dict):
                                mstates = mode_cfg.get('states', []) or []
                                if isinstance(mstates, list):
                                    collected.extend(str(s) for s in mstates)
            else:
                # Fallback parser: extract every states: [\"0\", \"1\", ...] occurrence
                for m in re.finditer(r'states:\s*\[(.*?)\]', yaml_text, re.DOTALL):
                    collected.extend(re.findall(r'\"([^\"]+)\"', m.group(1)))
            yaml_states = sorted(set(collected))
        except Exception:
            pass

    # 2. Find actual state files on disk
    pattern = f'.claude/skills/{skill}/state-*.md'
    disk_files = sorted(glob.glob(pattern))

    states = []
    for sf in disk_files:
        with open(sf) as f:
            lines = f.readlines()
        total_lines = len(lines)

        # 3. Count ### sub-headers in ACTIONS (excluding code fences)
        in_actions = False
        in_fence = False
        sub_headers = 0
        numbered_steps = 0
        current_section_lines = 0
        max_section_lines = 0
        artifact_writes = 0
        postcond_items = 0
        in_postcond = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith('\`\`\`'):
                in_fence = not in_fence
                continue
            if in_fence:
                # Count artifact writes inside code fences within ACTIONS
                if in_actions:
                    if re.search(r'(json\.dump|open\(.*[\"\\x27]w[\"\\x27]\)|cat\s*>|>\s*\.runs/|>\s*\.\./)', stripped):
                        artifact_writes += 1
                continue
            if stripped == '**ACTIONS:**':
                in_actions = True
                in_postcond = False
                continue
            if stripped == '**POSTCONDITIONS:**':
                in_actions = False
                in_postcond = True
                continue
            if stripped.startswith('**VERIFY'):
                in_postcond = False
                continue
            if in_actions and stripped.startswith('### '):
                max_section_lines = max(max_section_lines, current_section_lines)
                current_section_lines = 0
                sub_headers += 1
            elif in_actions:
                current_section_lines += 1
                if re.match(r'^\d+\.', stripped):
                    numbered_steps += 1
            if in_postcond and stripped.startswith('- '):
                postcond_items += 1
        max_section_lines = max(max_section_lines, current_section_lines)

        state_id = re.search(r'state-(.+?)\.md', sf)
        states.append({
            'id': state_id.group(1) if state_id else sf,
            'file': sf,
            'total_lines': total_lines,
            'actions_sub_headers': sub_headers,
            'actions_numbered_steps': numbered_steps,
            'actions_max_section_lines': max_section_lines,
            'intermediate_artifact_writes': artifact_writes,
            'postcondition_items': postcond_items
        })

    # 4. Cross-reference disk vs dispatch table AND skill.yaml states list.
    # Canonical state IDs = union of both authoritative sources. A state
    # file is orphaned only if it's missing from the union.
    disk_ids = [re.search(r'state-(.+?)\.md', f).group(1) for f in disk_files if re.search(r'state-(.+?)\.md', f)]
    canonical_ids = set(dispatch_ids) | set(yaml_states)
    orphan_files = [f for f, did in zip(disk_files, disk_ids) if did not in canonical_ids]

    manifest[skill] = {
        'command_file': cmd_file,
        'dispatch_state_ids': dispatch_ids,
        'skill_yaml_state_ids': yaml_states,
        'disk_state_count': len(disk_files),
        'orphan_state_files': orphan_files,
        'states': states
    }

os.makedirs('.runs', exist_ok=True)
print(f'Skill manifest: {len(manifest)} skills, {sum(s[\"disk_state_count\"] for s in manifest.values())} state files', file=sys.stderr)
print(json.dumps(manifest))
")
bash .claude/scripts/lib/write-gate-artifact.sh \
  --path .runs/audit-skill-manifest.json \
  --payload "$PAYLOAD" \
  --skill audit
```

Validator health baseline:
```bash
python3 scripts/validate-frontmatter.py 2>&1 | tail -1
python3 scripts/validate-semantics.py 2>&1 | tail -1
bash scripts/consistency-check.sh 2>&1 | tail -1
```

### Prior audit (delta tracking)

If `.runs/audit-manifest.json` exists from a prior run:
```bash
python3 -c "
import json
d = json.load(open('.runs/audit-manifest.json'))
print(f\"Prior audit: {d.get('timestamp','')} — {d.get('total_findings',0)} findings\")
for f in d.get('findings', []):
    print(f\"  [{f.get('dimension','')}] {f.get('title','')}\")
" 2>/dev/null || echo "No prior audit found"
```

Store prior findings as `prior_findings` for delta comparison in Step 2.

Merge audit-specific fields into context.
Substitute the parsed scope value (e.g., `full`, `hooks`, `commands`, `patterns`, `agents`, or `stacks`) into the command:
```bash
bash .claude/scripts/init-context.sh audit '{"scope":"<parsed scope value>"}'
```

**POSTCONDITIONS:**
- Scope parsed (full, hooks, commands, patterns, agents, or stacks)
- `save_manifest` flag set (true/false)
- Baseline metrics collected (file inventory, largest files, duplication signals, references, functions)
- Validator health baseline collected
- Prior audit findings loaded (if any)
- Skill manifest generated (`.runs/audit-skill-manifest.json`) if scope is `full` <!-- conditional: checked via scope field in audit-context.json -->
- `.runs/audit-context.json` exists

**VERIFY:**
```bash
test -f .runs/audit-context.json && python3 -c "import json,os; ctx=json.load(open('.runs/audit-context.json')); assert ctx.get('scope','')!='full' or os.path.exists('.runs/audit-skill-manifest.json'), 'full scope but manifest missing'"
```

**STATE TRACKING:** After postconditions pass, mark this state complete:
```bash
bash .claude/scripts/advance-state.sh audit 0
```

**NEXT:** Read [state-1-parallel-analysis.md](state-1-parallel-analysis.md) to continue.
