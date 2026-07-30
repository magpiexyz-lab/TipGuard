#!/usr/bin/env python3
"""verify-linter CLI bootstrap shim.

6-line entry point: resolve sys.path so the linter package can be imported,
then delegate to runner.main(). Keeps the relative-import-in-__main__ trap
out of runner.py — runner is always imported, never executed as __main__.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(os.path.dirname(HERE))  # .claude/scripts
sys.path.insert(0, SCRIPTS_DIR)
from lib.linter.runner import main  # noqa: E402
sys.exit(main())
