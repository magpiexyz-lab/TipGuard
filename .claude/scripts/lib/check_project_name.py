#!/usr/bin/env python3
"""check_project_name.py — Assert PROJECT_NAME constant matches experiment.yaml.name.

Closes the prose-only gap documented in:
  - .claude/stacks/analytics/posthog.md (rename guidance)
  - .claude/patterns/iterate-cross-debug-prompts.md (manual diagnosis)

Why this exists:
  - /bootstrap state-3 enforces `experiment.yaml.name` is kebab-case and writes
    that value verbatim into `PROJECT_NAME` in src/lib/analytics.ts and
    src/lib/analytics-server.ts at create time.
  - The template doc says PROJECT_NAME "Must NEVER be edited at runtime" but
    nothing enforces post-creation drift. Rename-then-redeploy without syncing
    the constant silently misattributes 100% of paid traffic to the wrong MVP
    until /iterate --cross archaeology surfaces it 90 days later.
  - This script runs at /verify (state-0, standalone mode) and /bootstrap
    (state-13a, state-13c gate-keeper). Drift fails the pipeline with a single
    actionable message instead of corrupting analytics silently.

Exit codes:
  0 — match; or no analytics files exist AND `stack.analytics` is absent
  1 — drift detected; stderr lists every offending file with actual vs.
      expected, plus a one-line fix instruction
  2 — environmental error (missing yaml, missing PyYAML, parse failure)

Usage:
  python3 .claude/scripts/lib/check_project_name.py
  python3 .claude/scripts/lib/check_project_name.py --yaml path/to/test.yaml
  python3 .claude/scripts/lib/check_project_name.py --root /tmp/sandbox    # tests
"""
from __future__ import annotations

import argparse
import os
import re
import sys

PROJECT_NAME_PATTERN = re.compile(
    r'^\s*(?:export\s+)?const\s+PROJECT_NAME\s*=\s*["\']([^"\']+)["\']\s*;',
    re.MULTILINE,
)

CANDIDATE_FILES = ('src/lib/analytics.ts', 'src/lib/analytics-server.ts')


def _resolve(root: str, rel: str) -> str:
    return rel if os.path.isabs(rel) else os.path.join(root, rel)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    parser.add_argument(
        '--yaml',
        default='experiment/experiment.yaml',
        help='Path to experiment.yaml (default: experiment/experiment.yaml relative to --root)',
    )
    parser.add_argument(
        '--root',
        default='.',
        help='Project root for resolving relative paths (default: cwd; override for tests)',
    )
    args = parser.parse_args(argv)

    yaml_path = _resolve(args.root, args.yaml)
    if not os.path.isfile(yaml_path):
        print(f'ERROR: {yaml_path} not found', file=sys.stderr)
        return 2

    try:
        import yaml as yamllib
    except ImportError:
        print('ERROR: PyYAML not available (pip install pyyaml)', file=sys.stderr)
        return 2

    try:
        with open(yaml_path) as fh:
            doc = yamllib.safe_load(fh) or {}
    except Exception as exc:
        print(f'ERROR: failed to parse {yaml_path}: {exc}', file=sys.stderr)
        return 2

    expected = str(doc.get('name') or '').strip()
    if not expected:
        print(f'ERROR: experiment.yaml.name is missing or empty', file=sys.stderr)
        return 2

    stack = doc.get('stack') or {}
    has_analytics_stack = bool((stack.get('analytics') or '').strip()) if isinstance(stack, dict) else False

    failures: list[tuple[str, str | None, str | None]] = []
    found_any = False
    for rel in CANDIDATE_FILES:
        path = _resolve(args.root, rel)
        if not os.path.isfile(path):
            continue
        found_any = True
        with open(path) as fh:
            content = fh.read()
        match = PROJECT_NAME_PATTERN.search(content)
        if not match:
            failures.append((rel, None, 'PROJECT_NAME constant not found'))
            continue
        actual = match.group(1).strip()
        if actual != expected:
            failures.append((rel, actual, None))

    if not found_any:
        if has_analytics_stack:
            print(
                'ERROR: stack.analytics is configured in experiment.yaml but '
                'neither src/lib/analytics.ts nor src/lib/analytics-server.ts exists.',
                file=sys.stderr,
            )
            print(
                'Fix: re-run /bootstrap or restore the analytics library file '
                'expected by the analytics stack.',
                file=sys.stderr,
            )
            return 1
        return 0

    if failures:
        print(
            f'PROJECT_NAME drift detected (experiment.yaml.name = "{expected}"):',
            file=sys.stderr,
        )
        for path, actual, msg in failures:
            if msg:
                print(f'  {path}: {msg}', file=sys.stderr)
            else:
                print(
                    f'  {path}: PROJECT_NAME = "{actual}" (expected "{expected}")',
                    file=sys.stderr,
                )
        print('', file=sys.stderr)
        print(
            f'Fix: change PROJECT_NAME to "{expected}" in each file above. '
            'PROJECT_NAME must equal experiment.yaml.name — analytics identity '
            'stability across deploys depends on this constant matching. '
            'See .claude/stacks/analytics/posthog.md for context.',
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
